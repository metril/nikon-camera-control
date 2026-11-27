"""Password store, session store, kiosk token and limiter (xdist-safe: tmp_path only)."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.core.auth import (
    SESSION_MAX_AGE_S,
    KioskToken,
    LoginLimiter,
    PasswordStore,
    SessionStore,
    sha256_hex,
)


def test_password_roundtrip_and_file_contents(tmp_path: Path) -> None:
    store = PasswordStore(tmp_path / "password.json")
    assert store.state == "none" and not store.is_set and not store.verify("x")
    store.set("correct horse")
    assert store.state == "set" and store.is_set
    assert store.verify("correct horse")
    assert not store.verify("correct horsf") and not store.verify("")
    raw = (tmp_path / "password.json").read_text()
    assert "correct horse" not in raw
    doc = json.loads(raw)
    assert (doc["scheme"], doc["n"], doc["r"], doc["p"]) == ("scrypt", 2**14, 8, 1)
    assert stat.S_IMODE((tmp_path / "password.json").stat().st_mode) == 0o600
    store.set("another one 1")  # new salt, old password no longer valid
    assert store.verify("another one 1") and not store.verify("correct horse")
    store.clear()
    assert store.state == "none"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        "{}",
        json.dumps({"scheme": "md5", "n": 16384, "r": 8, "p": 1, "salt": "AAAA", "hash": "AAAA"}),
        json.dumps(
            {"scheme": "scrypt", "n": 3, "r": 8, "p": 1, "salt": "AAAAAAAAAAA=", "hash": "x"}
        ),
        json.dumps(
            {"scheme": "scrypt", "n": 2**30, "r": 8, "p": 1, "salt": "AAAAAAAAAAA=", "hash": "AAAA"}
        ),
    ],
)
def test_corrupt_password_file_fails_closed(tmp_path: Path, content: str) -> None:
    f = tmp_path / "password.json"
    f.write_text(content)
    store = PasswordStore(f)
    assert store.state == "locked" and store.is_set  # still protected
    assert not store.verify("") and not store.verify("anything")
    f.unlink()  # host-side recovery works without a restart
    assert store.state == "none"


def test_password_notifies_listeners(tmp_path: Path) -> None:
    store = PasswordStore(tmp_path / "p.json")
    calls: list[int] = []
    unsub = store.subscribe(lambda: calls.append(1))
    store.set("password one")
    store.clear()
    unsub()
    store.set("password two")
    assert calls == [1, 1]


def test_sessions_hashed_at_rest_and_validate(tmp_path: Path) -> None:
    f = tmp_path / "sessions.json"
    s = SessionStore(f)
    token = s.create("browser", "UA/1")
    raw = f.read_text()
    assert token not in raw and sha256_hex(token) in raw
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    got = s.validate(token)
    assert got is not None and got[0].kind == "browser" and got[2] is False
    assert s.validate("nope") is None and s.validate(None) is None and s.validate("") is None
    again = SessionStore(f)  # survives a restart
    assert again.validate(token) is not None
    assert again.revoke_token(token) and again.validate(token) is None


@pytest.mark.parametrize("content", ["", "garbage", "{}", '{"sessions": [{"hash": "zz"}]}'])
def test_corrupt_sessions_file_means_no_valid_sessions(tmp_path: Path, content: str) -> None:
    f = tmp_path / "sessions.json"
    f.write_text(content)
    s = SessionStore(f)
    assert s.list() == []
    assert s.validate("whatever") is None
    assert s.validate(sha256_hex("x")) is None  # a hash is not a credential


def _age(f: Path, days: float) -> None:
    doc = json.loads(f.read_text())
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    for r in doc["sessions"]:
        r["last_seen"] = old
    f.write_text(json.dumps(doc))


def test_session_refresh_due_and_expiry(tmp_path: Path) -> None:
    f = tmp_path / "sessions.json"
    s = SessionStore(f)
    token = s.create("browser")
    _age(f, 2)
    s = SessionStore(f)
    got = s.validate(token)
    assert got is not None and got[2] is True  # older than a day: refresh the cookie
    got = s.validate(token)
    assert got is not None and got[2] is False  # last_seen was bumped
    _age(f, SESSION_MAX_AGE_S / 86400 + 1)
    s = SessionStore(f)
    assert s.validate(token) is None and s.list() == []


def test_revocations_and_caps(tmp_path: Path) -> None:
    s = SessionStore(tmp_path / "s.json")
    a, b = s.create("browser"), s.create("browser")
    k = s.create("kiosk")
    ids = {x.id for x in s.list()}
    assert len(ids) == 3
    a_id = sha256_hex(a)[:16]
    assert s.revoke_browsers_except(a_id) == 1
    assert s.validate(a) is not None and s.validate(b) is None and s.validate(k) is not None
    assert s.revoke_kind("kiosk") == 1 and s.validate(k) is None
    assert s.revoke_id("nonexistent") is False
    for _ in range(15):
        s.create("kiosk")
    assert sum(1 for x in s.list() if x.kind == "kiosk") == 10


def test_revocation_notifies(tmp_path: Path) -> None:
    s = SessionStore(tmp_path / "s.json")
    t = s.create("browser")
    calls: list[int] = []
    s.subscribe(lambda: calls.append(1))
    s.revoke_token(t)
    assert calls == [1]


def test_kiosk_token_created_with_modes_and_verified(tmp_path: Path) -> None:
    d = tmp_path / "kiosk-auth"
    k = KioskToken(d)
    assert k.read() is None and not k.verify("x")
    k.ensure()
    token = k.read()
    assert token is not None and len(token) >= 32
    assert k.path.read_text() == token + "\n"  # a single line
    assert stat.S_IMODE(k.path.stat().st_mode) == 0o644
    assert stat.S_IMODE(d.stat().st_mode) == 0o755
    assert k.verify(token) and not k.verify(token + "x") and not k.verify("") and not k.verify("é")
    k.ensure()  # idempotent: the token is kept
    assert k.read() == token
    k.rotate()
    new = k.read()
    assert new is not None and new != token and not k.verify(token) and k.verify(new)


@pytest.mark.parametrize("content", ["", "short", "\n", "x" * 31, "é" * 40])
def test_unusable_kiosk_token_is_replaced_and_never_matches(tmp_path: Path, content: str) -> None:
    k = KioskToken(tmp_path)
    k.path.write_text(content, encoding="utf-8")
    assert k.read() is None
    assert not k.verify(content)  # fail closed
    k.ensure()
    assert k.read() is not None


def test_kiosk_ensure_never_raises_when_unwritable(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    k = KioskToken(blocker / "sub")  # mkdir under a file fails
    k.ensure()
    assert k.read() is None and not k.verify("anything")


def test_limiter_per_ip_total_window_and_forgive() -> None:
    now = [1000.0]
    lim = LoginLimiter(clock=lambda: now[0])
    for _ in range(5):
        wait, _m = lim.attempt("1.1.1.1")
        assert wait == 0
    wait, _m = lim.attempt("1.1.1.1")
    assert 0 < wait <= 300  # 6th attempt blocked
    assert lim.attempt("2.2.2.2")[0] == 0  # another client is unaffected
    now[0] += 301
    assert lim.attempt("1.1.1.1")[0] == 0  # window passed

    wait, mark = lim.attempt("3.3.3.3")
    lim.forgive("3.3.3.3", mark)  # a success does not count
    for _ in range(5):
        assert lim.attempt("3.3.3.3")[0] == 0

    now[0] += 301
    lim = LoginLimiter(clock=lambda: now[0])
    for i in range(30):
        assert lim.attempt(f"10.0.0.{i}")[0] == 0
    assert lim.attempt("10.9.9.9")[0] > 0  # global cap across many IPs
