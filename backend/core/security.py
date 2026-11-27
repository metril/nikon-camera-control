"""Request authentication: optional API key, app-password sessions and the kiosk token.

Only a sha256 hash of the API key is ever stored (see ``backend.core.auth`` for sessions)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, Request, Response, WebSocket
from fastapi.security import APIKeyCookie, APIKeyHeader

from backend.core.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_S,
    AuthContext,
    AuthState,
)
from backend.core.errors import Unauthorized

log = logging.getLogger(__name__)

# Stored in place of the key hash when api_key.json exists but is unusable: never equals a
# sha256 hex digest, so every key is rejected (fail closed).
LOCKED_HASH = "!locked"

# Registers the header as an OpenAPI security scheme; enforcement is in require_api_key.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
session_cookie = APIKeyCookie(name=SESSION_COOKIE, auto_error=False)


def hash_api_key(key: str) -> str:
    """Hex sha256 of the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str | None, key_hash: str | None) -> bool:
    """True if no hash is configured (open mode) or sha256(key) matches via compare_digest."""
    if not key_hash:
        return True
    if not key:
        return False
    return hmac.compare_digest(hash_api_key(key), key_hash)


class ApiKeyStore:
    """The API key hash, kept in its own file (``{"sha256", "created"}``), written atomically.

    Missing file = no key (open mode). Present but unreadable/invalid = FAIL CLOSED
    (``load`` returns ``LOCKED_HASH``). Recovery from lockout: delete the file on the host.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> str | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            return self._locked(f"unreadable: {exc}")
        try:
            data = json.loads(raw)
            digest = data["sha256"]
            if not (isinstance(digest, str) and len(digest) == 64):
                raise ValueError("sha256 must be a 64-character hex string")
            int(digest, 16)
        except (ValueError, KeyError, TypeError) as exc:
            return self._locked(f"invalid: {exc!r}")
        return digest

    def _locked(self, why: str) -> str:
        log.error(
            "API key file %s is %s. Authentication stays ENABLED and every key is rejected. "
            "Delete this file on the host to remove the key and re-open the app.",
            self._path,
            why,
        )
        return LOCKED_HASH

    def save(self, key_hash: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".api_key-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"sha256": key_hash, "created": datetime.now(UTC).isoformat()}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


def generate_api_key() -> str:
    """New random URL-safe key (shown to the user once)."""
    return secrets.token_urlsafe(32)


def _current_hash(state: object) -> str | None:
    store = getattr(state, "config_store", None)
    return store.config.api_key_hash if store is not None else None


def _auth_state(state: object) -> AuthState | None:
    auth = getattr(state, "auth", None)
    return auth if isinstance(auth, AuthState) else None


def is_protected(state: object) -> bool:
    """True when an API key or an app password exists (a locked password file counts)."""
    auth = _auth_state(state)
    return bool(_current_hash(state)) or (auth is not None and auth.password.is_set)


def _key_valid(key: str | None, key_hash: str | None) -> bool:
    """Strict: False when no key is configured (unlike ``verify_api_key``, which means open)."""
    return bool(key_hash) and bool(key) and verify_api_key(key, key_hash)


def authenticate(
    state: object, key: str | None, cookie: str | None
) -> tuple[AuthContext | None, bool]:
    """(context, refresh_cookie) or (None, False) when the credentials do not allow access.

    Allowed when the app is open, the API key matches, or the session cookie is a live session.
    A valid session is reported even in open mode (so "current session" works there).
    """
    auth = _auth_state(state)
    session = auth.sessions.validate(cookie) if auth is not None else None
    key_hash = _current_hash(state)
    if _key_valid(key, key_hash):
        return AuthContext("key"), False
    if session is not None:
        info, h, due = session
        return AuthContext("session", info.id, h, info.kind), due
    if not is_protected(state):
        return AuthContext("open"), False
    return None, False


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_S,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


async def require_api_key(
    request: Request,
    response: Response,
    _key: str | None = Depends(api_key_header),
    _cookie: str | None = Depends(session_cookie),
) -> None:
    """FastAPI dependency for REST routes (name kept: it guards every protected route).

    Allowed when the app is open (no password and no key), ``X-API-Key`` is valid, or the
    ``ncc_session`` cookie is a live session. Both are read live, so changes apply at once.
    Raises ``Unauthorized`` (401) otherwise. Health, docs and the SPA do not use it. The result
    is kept on ``request.state.auth``; a session due for its daily refresh gets a fresh cookie.
    """
    ctx, refresh = authenticate(request.app.state, _key, _cookie)
    if ctx is None:
        raise Unauthorized()
    request.state.auth = ctx
    if refresh and _cookie:
        set_session_cookie(response, _cookie, secure=request.url.scheme == "https")


def current_auth(request: Request) -> AuthContext:
    """The context set by ``require_api_key`` (for routes that also depend on it)."""
    ctx = getattr(request.state, "auth", None)
    if not isinstance(ctx, AuthContext):
        raise Unauthorized()
    return ctx


async def ws_authorize(websocket: WebSocket) -> bool:
    """Authorize a WebSocket; call before accepting.

    Credentials: the ``apikey.<key>`` subprotocol (never the URL, which would leak it into
    access logs) or the ``ncc_session`` cookie. Returns True if allowed (always in open mode);
    the caller then accepts, echoing ``ws_subprotocol``. On failure it accepts and closes with
    4401 (closing before accept would surface as HTTP 403) and returns False; the caller must
    then return. After accepting, use ``AuthWatch`` to end the socket when access is lost.
    """
    proto = ws_subprotocol(websocket)
    key = proto.removeprefix("apikey.") if proto else None
    ctx, _ = authenticate(websocket.app.state, key, websocket.cookies.get(SESSION_COOKIE))
    if ctx is not None:
        websocket.state.auth_session_hash = ctx.session_hash if ctx.method == "session" else None
        return True
    await websocket.accept(subprotocol=proto)
    await websocket.close(code=4401, reason="Missing or invalid credentials")
    return False


class AuthWatch:
    """Fires ``changed`` when the socket's access is lost or the app becomes protected.

    Create it right after a successful ``ws_authorize`` (before any await). It fires when the
    API key hash changes, the session the socket used is revoked, or the app goes from open to
    protected (a password or key was first set). Call ``close()`` when the handler ends.
    """

    def __init__(self, websocket: WebSocket) -> None:
        state = websocket.app.state
        store = state.config_store
        auth = _auth_state(state)
        loop = asyncio.get_running_loop()
        self.changed = asyncio.Event()
        start_hash = store.config.api_key_hash
        was_open = not is_protected(state)
        session_hash: str | None = getattr(websocket.state, "auth_session_hash", None)
        unsubs: list[Callable[[], None]] = []

        def check() -> None:
            if (
                _current_hash(state) != start_hash
                or (was_open and is_protected(state))
                or (session_hash and auth is not None and not auth.sessions.has_hash(session_hash))
            ):
                loop.call_soon_threadsafe(self.changed.set)

        unsubs.append(store.subscribe(lambda new, old: check()))
        if auth is not None:
            unsubs.append(auth.sessions.subscribe(check))
            unsubs.append(auth.password.subscribe(check))
        self._unsubscribe = unsubs
        check()  # changed between the credential check and now

    def close(self) -> None:
        for unsub in self._unsubscribe:
            unsub()


def ws_subprotocol(websocket: WebSocket) -> str | None:
    """The ``apikey.<key>`` subprotocol offered by the client, if any (echo it on accept)."""
    for proto in websocket.scope.get("subprotocols", []):
        if proto.startswith("apikey."):
            return str(proto)
    return None
