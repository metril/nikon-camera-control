"""Browser sign-in: app password, sessions, kiosk device token and the login rate limiter.

Secrets are never logged. Every comparison of secret material uses ``hmac.compare_digest``.
Anything unreadable fails closed: a bad password file means "protected, nobody can sign in"
(delete the file on the host to recover); a bad sessions file means "no valid sessions".
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

SESSION_COOKIE = "ncc_session"
SESSION_MAX_AGE_S = 400 * 24 * 3600
SESSION_REFRESH_S = 24 * 3600
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SCRYPT_MAX_N = 2**20  # bound for params read from disk (a tampered file must not DoS us)
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 256
KIOSK_TOKEN_FILE = "kiosk-token"  # noqa: S105
MAX_BROWSER_SESSIONS = 100
MAX_KIOSK_SESSIONS = 10

SessionKind = Literal["browser", "kiosk"]


def _atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ password
def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=256 * n * r + (1 << 20)
    )


@dataclass(frozen=True)
class PasswordRecord:
    salt: bytes
    digest: bytes
    n: int
    r: int
    p: int


PasswordState = Literal["none", "set", "locked"]


class PasswordStore:
    """The app password as an scrypt hash in ``password.json``, written atomically.

    Missing file = no password. Present but unusable = ``locked`` (protected, every password
    rejected). Reads are cached by file stat so deleting the file on the host re-opens the app.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._cache: tuple[object, PasswordState, PasswordRecord | None] | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[], None]] = []

    @property
    def path(self) -> Path:
        return self._path

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                log.exception("password listener failed")

    def _load(self) -> tuple[PasswordState, PasswordRecord | None]:
        try:
            st = self._path.stat()
        except FileNotFoundError:
            return "none", None
        except OSError as exc:
            log.error("Password file %s is unreadable (%s); app stays PROTECTED", self._path, exc)
            return "locked", None
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        with self._lock:
            if self._cache is not None and self._cache[0] == sig:
                return self._cache[1], self._cache[2]
            state, rec = self._read()
            self._cache = (sig, state, rec)
            return state, rec

    def _read(self) -> tuple[PasswordState, PasswordRecord | None]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data.get("scheme") != "scrypt":
                raise ValueError("unknown scheme")
            n, r, p = int(data["n"]), int(data["r"]), int(data["p"])
            if not (2 <= n <= SCRYPT_MAX_N and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 16):
                raise ValueError("scrypt parameters out of range")
            salt = base64.b64decode(data["salt"], validate=True)
            digest = base64.b64decode(data["hash"], validate=True)
            if len(salt) < 8 or len(digest) < 16:
                raise ValueError("salt or hash too short")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.error(
                "Password file %s is invalid (%s). The app stays PROTECTED and no password works. "
                "Delete the file on the host to remove the password.",
                self._path,
                type(exc).__name__,
            )
            return "locked", None
        return "set", PasswordRecord(salt, digest, n, r, p)

    @property
    def state(self) -> PasswordState:
        return self._load()[0]

    @property
    def is_set(self) -> bool:
        """True when a password exists or the file is locked (both mean protected)."""
        return self.state != "none"

    def verify(self, password: str) -> bool:
        """Constant-time check; always False when absent or locked. CPU-heavy: run in a thread."""
        state, rec = self._load()
        if state != "set" or rec is None or len(password) > MAX_PASSWORD_LEN:
            return False
        try:
            got = _scrypt(password, rec.salt, rec.n, rec.r, rec.p)
        except (ValueError, MemoryError):
            return False
        return hmac.compare_digest(got, rec.digest)

    def set(self, password: str) -> None:
        salt = secrets.token_bytes(16)
        digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        doc = {
            "scheme": "scrypt",
            "n": SCRYPT_N,
            "r": SCRYPT_R,
            "p": SCRYPT_P,
            "salt": base64.b64encode(salt).decode(),
            "hash": base64.b64encode(digest).decode(),
            "created": datetime.now(UTC).isoformat(),
        }
        _atomic_write(self._path, json.dumps(doc), 0o600)
        self._notify()

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()
        self._notify()


# ------------------------------------------------------------------ sessions
@dataclass
class SessionInfo:
    id: str  # public handle (prefix of the stored hash); not usable as a credential
    kind: SessionKind
    created: datetime
    last_seen: datetime
    user_agent: str | None


class SessionStore:
    """Sessions in ``sessions.json``; only sha256 of each token is stored."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._listeners: list[Callable[[], None]] = []
        self._load()

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb) if cb in self._listeners else None

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:
                log.exception("session listener failed")

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            log.error("Sessions file %s unreadable (%s); no session is valid", self._path, exc)
            return
        try:
            parsed = []
            for r in json.loads(raw)["sessions"]:
                h = r["hash"]
                if not (isinstance(h, str) and len(h) == 64):
                    raise ValueError("bad hash")
                int(h, 16)
                if r["kind"] not in ("browser", "kiosk"):
                    raise ValueError("bad kind")
                datetime.fromisoformat(r["created"])
                datetime.fromisoformat(r["last_seen"])
                parsed.append(r)
        except (ValueError, KeyError, TypeError) as exc:
            log.error(
                "Sessions file %s is invalid (%s); no session is valid (everyone signs in again)",
                self._path,
                type(exc).__name__,
            )
            return
        self._rows = parsed

    def _save(self) -> None:
        _atomic_write(self._path, json.dumps({"sessions": self._rows}), 0o600)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _find(self, token_hash: str) -> dict[str, Any] | None:
        found = None
        for r in self._rows:  # no early exit: constant work per lookup
            if hmac.compare_digest(r["hash"], token_hash):
                found = r
        return found

    def create(self, kind: SessionKind, user_agent: str | None = None) -> str:
        """New session; returns the cookie token (shown once, never stored)."""
        token = secrets.token_urlsafe(32)
        now = self._now().isoformat()
        row = {
            "hash": sha256_hex(token),
            "kind": kind,
            "created": now,
            "last_seen": now,
            "ua": (user_agent or "")[:200] or None,
        }
        with self._lock:
            self._rows.append(row)
            cap = MAX_KIOSK_SESSIONS if kind == "kiosk" else MAX_BROWSER_SESSIONS
            same = sorted(
                (r for r in self._rows if r["kind"] == kind), key=lambda r: r["last_seen"]
            )
            for old in same[: max(0, len(same) - cap)]:
                self._rows.remove(old)
            self._save()
        self._notify()
        return token

    def validate(self, token: str | None) -> tuple[SessionInfo, str, bool] | None:
        """(session, token hash, due_for_refresh) for a live token, else None.

        Expired rows are dropped. ``due`` also bumps ``last_seen`` (at most once a day).
        """
        if not token or len(token) > 200:
            return None
        h = sha256_hex(token)
        with self._lock:
            row = self._find(h)
            if row is None:
                return None
            age = (self._now() - datetime.fromisoformat(row["last_seen"])).total_seconds()
            if age > SESSION_MAX_AGE_S:
                self._rows.remove(row)
                with contextlib.suppress(OSError):
                    self._save()
                return None
            due = age > SESSION_REFRESH_S
            if due:
                row["last_seen"] = self._now().isoformat()
                with contextlib.suppress(OSError):
                    self._save()
            return self._info(row), h, due

    def has_hash(self, token_hash: str) -> bool:
        with self._lock:
            return self._find(token_hash) is not None

    @staticmethod
    def _info(row: dict[str, Any]) -> SessionInfo:
        return SessionInfo(
            id=row["hash"][:16],
            kind=row["kind"],
            created=datetime.fromisoformat(row["created"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            user_agent=row.get("ua"),
        )

    def list(self) -> list[SessionInfo]:
        with self._lock:
            return [self._info(r) for r in self._rows]

    def _remove(self, pred: Callable[[dict[str, Any]], bool]) -> int:
        with self._lock:
            keep = [r for r in self._rows if not pred(r)]
            n = len(self._rows) - len(keep)
            if n:
                self._rows = keep
                self._save()
        if n:
            self._notify()
        return n

    def revoke_token(self, token: str) -> bool:
        h = sha256_hex(token)
        return self._remove(lambda r: hmac.compare_digest(r["hash"], h)) > 0

    def revoke_id(self, session_id: str) -> bool:
        return self._remove(lambda r: r["hash"][:16] == session_id) > 0

    def revoke_kind(self, kind: SessionKind) -> int:
        return self._remove(lambda r: r["kind"] == kind)

    def revoke_browsers_except(self, keep_id: str | None) -> int:
        return self._remove(lambda r: r["kind"] == "browser" and r["hash"][:16] != keep_id)


# ------------------------------------------------------------------ kiosk token
class KioskToken:
    """The kiosk device token: one line in ``<dir>/kiosk-token`` (0644 in a 0755 directory).

    The file is read on every check, so the file on disk is the single source of truth.
    """

    MIN_LEN = 32

    def __init__(self, directory: Path) -> None:
        self._dir = Path(directory)
        self._file = self._dir / KIOSK_TOKEN_FILE

    @property
    def path(self) -> Path:
        return self._file

    def read(self) -> str | None:
        try:
            token = self._file.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return None
        return token if len(token) >= self.MIN_LEN and token.isascii() else None

    def ensure(self) -> None:
        """Create the directory and token if missing or unusable. Never raises."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(self._dir, 0o755)  # noqa: S103 - the kiosk container must read it
            if self.read() is None:
                self.rotate()
            else:
                with contextlib.suppress(OSError):
                    os.chmod(self._file, 0o644)
        except OSError as exc:
            log.error("Kiosk token unavailable in %s (%s); kiosk pairing is off", self._dir, exc)

    def rotate(self) -> None:
        _atomic_write(self._file, secrets.token_urlsafe(32) + "\n", 0o644)

    def verify(self, candidate: str) -> bool:
        token = self.read()
        if token is None or not candidate or len(candidate) > 200 or not candidate.isascii():
            return False
        return hmac.compare_digest(candidate.encode("ascii"), token.encode("ascii"))


# ------------------------------------------------------------------ rate limiter
class LoginLimiter:
    """5 failed attempts per client IP or 30 in total within 5 minutes lock further attempts out."""

    def __init__(
        self,
        per_ip: int = 5,
        total: int = 30,
        window_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_ip, self._total, self._window = per_ip, total, window_s
        self._clock = clock
        self._by_ip: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._ok: dict[str, float] = {}  # ip -> last success (exempt from the total cap)
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        cut = now - self._window
        while self._all and self._all[0] <= cut:
            self._all.popleft()
        for ip in list(self._by_ip):
            q = self._by_ip[ip]
            while q and q[0] <= cut:
                q.popleft()
            if not q:
                del self._by_ip[ip]
        for ip in [i for i, t in self._ok.items() if t <= cut]:
            del self._ok[ip]

    def attempt(self, ip: str) -> tuple[float, float]:
        """(retry_after_s, mark). Records the attempt up front (so a parallel burst cannot
        outrun the limit) unless already blocked; call ``forgive`` when it succeeds."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            wait = 0.0
            q = self._by_ip.get(ip)
            if q and len(q) >= self._per_ip:
                wait = max(wait, q[-self._per_ip] + self._window - now)
            if ip not in self._ok and len(self._all) >= self._total:
                wait = max(wait, self._all[-self._total] + self._window - now)
            if wait > 0:
                return wait, 0.0
            self._all.append(now)
            self._by_ip.setdefault(ip, deque()).append(now)
            return 0.0, now

    def forgive(self, ip: str, mark: float) -> None:
        """Remove one recorded attempt (it succeeded); the IP is then exempt from the total cap
        for one window, so a flood of failures from others cannot lock out a known-good client."""
        with self._lock:
            self._ok[ip] = self._clock()
            with contextlib.suppress(ValueError):
                self._all.remove(mark)
            q = self._by_ip.get(ip)
            if q is not None:
                with contextlib.suppress(ValueError):
                    q.remove(mark)
                if not q:
                    del self._by_ip[ip]


class KioskCodes:
    """Single-use pairing codes (30 s, in memory) traded for a kiosk session.

    The kiosk exchanges its device token for a code, so the long-lived token never appears in
    the browser's command line or URL history.
    """

    TTL_S = 30.0
    MAX = 16

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._codes: dict[str, float] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        for c in [c for c, exp in self._codes.items() if exp <= now]:
            del self._codes[c]

    def issue(self) -> str:
        code = secrets.token_urlsafe(24)
        with self._lock:
            now = self._clock()
            self._purge(now)
            while len(self._codes) >= self.MAX:
                del self._codes[min(self._codes, key=lambda c: self._codes[c])]
            self._codes[code] = now + self.TTL_S
        return code

    def redeem(self, code: str) -> bool:
        with self._lock:
            self._purge(self._clock())
            return self._codes.pop(code, None) is not None


@dataclass(frozen=True)
class AuthContext:
    """How a request authenticated and, for a cookie, which session."""

    method: Literal["open", "key", "session"]
    session_id: str | None = None
    session_hash: str | None = None
    kind: SessionKind | None = None


class AuthState:
    """The auth services of one app (``app.state.auth``)."""

    def __init__(self, data_dir: Path, kiosk_dir: Path) -> None:
        self.password = PasswordStore(data_dir / "password.json")
        self.sessions = SessionStore(data_dir / "sessions.json")
        self.kiosk = KioskToken(kiosk_dir)
        self.limiter = LoginLimiter()
        self.kiosk_limiter = LoginLimiter()  # kiosk pairing never shares the login budget
        self.kiosk_codes = KioskCodes()
        self.hash_slots = asyncio.Semaphore(2)  # concurrent scrypt hashes
