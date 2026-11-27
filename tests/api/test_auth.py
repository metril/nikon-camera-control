"""Browser sign-in: password, sessions, kiosk pairing, rate limit and WebSocket auth."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.core.auth import SESSION_COOKIE

A = "/api/v1/auth"
PROTECTED = "/api/v1/config"  # any route behind require_api_key
PW = "correct horse battery"
EVIL = {"Origin": "http://evil.example"}


async def _set_pw(
    client: httpx.AsyncClient, pw: str = PW, key: str | None = None
) -> httpx.Response:
    headers = {"X-API-Key": key} if key else {}
    r = await client.put(f"{A}/password", json={"new": pw}, headers=headers)
    assert r.status_code == 200, r.text
    return r


async def _key(client: httpx.AsyncClient) -> str:
    return str((await client.post("/api/v1/config/api-key")).json()["api_key"])


async def _fresh(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def _pair(c: httpx.AsyncClient, token: str) -> httpx.Response:
    """Kiosk flow: token -> single-use code -> session. Returns the pairing response (or the
    code response when that already failed)."""
    r = await c.post(f"{A}/kiosk/code", json={"token": token})
    if r.status_code != 200:
        return r
    return await c.post(f"{A}/kiosk", json={"code": r.json()["code"]})


@pytest.fixture
async def other(app: FastAPI, client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """A second browser (own cookie jar) on the same app."""
    async for c in _fresh(app):
        yield c


# ---------------------------------------------------------------- decision table
async def test_open_mode_allows_everything_and_status_says_so(client: httpx.AsyncClient) -> None:
    assert (await client.get(PROTECTED)).status_code == 200
    s = (await client.get(f"{A}/status")).json()
    assert s == {
        "auth_required": False,
        "password_set": False,
        "api_key_set": False,
        "authenticated": True,
        "session_kind": None,
    }
    assert (await client.get("/api/v1/info")).json()["password_set"] is False


async def test_decision_table_password_only(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    assert (await other.get(PROTECTED)).status_code == 401  # no credential
    assert (await other.get(PROTECTED, headers={"X-API-Key": "x"})).status_code == 401
    forged = {"Cookie": f"{SESSION_COOKIE}=forged"}
    assert (await other.get(PROTECTED, headers=forged)).status_code == 401
    assert (await client.get(PROTECTED)).status_code == 200  # the cookie set by PUT
    info = (await client.get("/api/v1/info")).json()
    assert info["password_set"] is True and info["auth_enabled"] is True
    s = (await other.get(f"{A}/status")).json()
    assert s["auth_required"] and s["password_set"] and not s["api_key_set"]
    assert s["authenticated"] is False


async def test_decision_table_key_only(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    key = await _key(client)
    assert (await other.get(PROTECTED)).status_code == 401
    assert (await other.get(PROTECTED, headers={"X-API-Key": key})).status_code == 200
    assert (await other.get(PROTECTED, headers={"X-API-Key": key + "x"})).status_code == 401
    s = (await other.get(f"{A}/status")).json()
    assert s["auth_required"] and s["api_key_set"] and not s["password_set"]
    # the key signs a browser in only while no password is set
    r = await other.post(f"{A}/login", json={"api_key": key})
    assert (
        r.status_code == 200
        and r.json()["authenticated"]
        and SESSION_COOKIE in r.headers["set-cookie"]
    )
    assert (await other.get(PROTECTED)).status_code == 200


async def test_decision_table_key_and_password(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    key = await _key(client)
    await _set_pw(client, key=key)
    assert (await other.get(PROTECTED, headers={"X-API-Key": key})).status_code == 200  # scripts
    assert (await other.post(f"{A}/login", json={"api_key": key})).status_code == 401  # not a login
    assert (await other.post(f"{A}/login", json={"password": "wrong password"})).status_code == 401
    assert (await other.post(f"{A}/login", json={"password": PW})).status_code == 200
    assert (await other.get(PROTECTED)).status_code == 200


async def test_login_in_open_mode_is_refused(client: httpx.AsyncClient) -> None:
    assert (await client.post(f"{A}/login", json={"password": PW})).status_code == 401
    assert (await client.post(f"{A}/login", json={"api_key": "x"})).status_code == 401


async def test_login_body_must_have_exactly_one_credential(client: httpx.AsyncClient) -> None:
    for body in ({}, {"password": "a", "api_key": "b"}):
        assert (await client.post(f"{A}/login", json=body)).status_code == 422


# ---------------------------------------------------------------- cookie flags
async def test_cookie_flags_http_and_https(app: FastAPI, client: httpx.AsyncClient) -> None:
    r = await _set_pw(client)
    c = r.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in c and "httponly" in c and "samesite=lax" in c
    assert f"max-age={400 * 24 * 3600}" in c and "path=/" in c and "secure" not in c
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://t") as tls:
        r2 = await tls.post(f"{A}/login", json={"password": PW})
        assert "secure" in r2.headers["set-cookie"].lower()


async def test_cookie_value_is_not_stored_in_clear(
    client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    await _set_pw(client)
    token = client.cookies[SESSION_COOKIE]
    for name in ("sessions.json", "password.json"):
        assert token not in (tmp_dirs.data_dir / name).read_text()
        assert PW not in (tmp_dirs.data_dir / name).read_text()


async def test_stale_session_gets_refreshed_cookie(
    app: FastAPI, client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    await _set_pw(client)
    f = tmp_dirs.data_dir / "sessions.json"
    doc = json.loads(f.read_text())
    doc["sessions"][0]["last_seen"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    f.write_text(json.dumps(doc))
    app.state.auth.sessions.__init__(f)  # reload from disk
    r = await client.get(PROTECTED)
    assert r.status_code == 200 and f"{SESSION_COOKIE}=" in r.headers["set-cookie"]
    assert "set-cookie" not in (await client.get(PROTECTED)).headers  # only once a day


# ---------------------------------------------------------------- password lifecycle
async def test_set_change_remove_password(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    await other.post(f"{A}/login", json={"password": PW})
    assert (await other.get(PROTECTED)).status_code == 200
    # change needs the current password
    assert (await client.put(f"{A}/password", json={"new": "brand new pass"})).status_code == 403
    r = await client.put(f"{A}/password", json={"current": "nope nope", "new": "brand new pass"})
    assert r.status_code == 403
    r = await client.put(f"{A}/password", json={"current": PW, "new": "brand new pass"})
    assert r.status_code == 200
    # the other browser was signed out, this one stays in, the old password is dead
    assert (await other.get(PROTECTED)).status_code == 401
    assert (await client.get(PROTECTED)).status_code == 200
    assert (await other.post(f"{A}/login", json={"password": PW})).status_code == 401
    assert (await other.post(f"{A}/login", json={"password": "brand new pass"})).status_code == 200
    # too short is rejected by validation
    assert (
        await client.put(f"{A}/password", json={"current": "brand new pass", "new": "short"})
    ).status_code == 422
    # removing needs the current password too
    assert (
        await client.request("DELETE", f"{A}/password", json={"current": "x"})
    ).status_code == 403
    r = await client.request("DELETE", f"{A}/password", json={"current": "brand new pass"})
    assert r.status_code == 200 and r.json()["auth_required"] is False
    assert r.json()["authenticated"] is True  # open mode again
    assert (await other.get(PROTECTED)).status_code == 200
    assert (
        await client.request("DELETE", f"{A}/password", json={"current": "x"})
    ).status_code == 409


async def test_remove_password_with_key_set_returns_to_key_only(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    key = await _key(client)
    await _set_pw(client, key=key)
    r = await client.request("DELETE", f"{A}/password", json={"current": PW})
    assert r.status_code == 200 and r.json()["authenticated"] is False  # browser sessions revoked
    assert r.json()["auth_required"] is True
    assert (await client.get(PROTECTED)).status_code == 401
    assert (await other.get(PROTECTED, headers={"X-API-Key": key})).status_code == 200


async def test_set_password_with_api_key_header_creates_session(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    key = await _key(client)
    r = await other.put(f"{A}/password", json={"new": PW}, headers={"X-API-Key": key})
    assert r.status_code == 200 and r.json()["session_kind"] == "browser"
    assert (await other.get(PROTECTED)).status_code == 200


async def test_locked_password_file_fails_closed(
    client: httpx.AsyncClient, other: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    (tmp_dirs.data_dir / "password.json").write_text("garbage")
    assert (await client.get(PROTECTED)).status_code == 401
    s = (await client.get(f"{A}/status")).json()
    assert s["auth_required"] and s["password_set"] and not s["authenticated"]
    assert (await client.post(f"{A}/login", json={"password": "garbage"})).status_code == 401
    (tmp_dirs.data_dir / "password.json").unlink()  # host-side recovery
    assert (await other.get(PROTECTED)).status_code == 200


async def test_corrupt_sessions_file_means_signed_out(
    app: FastAPI, client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    await _set_pw(client)
    (tmp_dirs.data_dir / "sessions.json").write_text("{broken")
    app.state.auth.sessions.__init__(tmp_dirs.data_dir / "sessions.json")
    assert (await client.get(PROTECTED)).status_code == 401


# ---------------------------------------------------------------- sessions
async def test_sessions_list_revoke_and_logout(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    await other.post(f"{A}/login", json={"password": PW}, headers={"User-Agent": "Other/1"})
    rows = (await client.get(f"{A}/sessions")).json()["sessions"]
    assert len(rows) == 2 and [r["current"] for r in rows].count(True) == 1
    assert "hash" not in json.dumps(rows) and {r["kind"] for r in rows} == {"browser"}
    theirs = next(r for r in rows if not r["current"])
    assert theirs["user_agent"] == "Other/1"
    assert (await client.delete(f"{A}/sessions/{theirs['id']}")).status_code == 200
    assert (await other.get(PROTECTED)).status_code == 401
    assert (await client.delete(f"{A}/sessions/{theirs['id']}")).status_code == 404
    # logout is open, revokes this session and clears the cookie
    r = await client.post(f"{A}/logout")
    assert r.status_code == 200 and f"{SESSION_COOKIE}=" in r.headers["set-cookie"]
    assert (await client.get(PROTECTED)).status_code == 401
    assert (await client.post(f"{A}/logout")).status_code == 200  # idempotent, signed out


async def test_revoke_all_keeps_current_and_kiosk(
    app: FastAPI, client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    await other.post(f"{A}/login", json={"password": PW})
    token = app.state.auth.kiosk.read()
    async for kiosk in _fresh(app):
        assert (await _pair(kiosk, token)).status_code == 200
        r = await client.post(f"{A}/sessions/revoke-all")
        assert r.json() == {"revoked": 1}
        assert (await other.get(PROTECTED)).status_code == 401
        assert (await client.get(PROTECTED)).status_code == 200
        assert (await kiosk.get(PROTECTED)).status_code == 200


async def test_sessions_require_auth(other: httpx.AsyncClient, client: httpx.AsyncClient) -> None:
    await _set_pw(client)
    assert (await other.get(f"{A}/sessions")).status_code == 401
    assert (await other.post(f"{A}/sessions/revoke-all")).status_code == 401
    assert (await other.post(f"{A}/kiosk-token/rotate")).status_code == 401
    assert (await other.put(f"{A}/password", json={"new": "hacked password"})).status_code == 401
    assert (await other.request("DELETE", f"{A}/password", json={"current": PW})).status_code == 401


# ---------------------------------------------------------------- rate limit
async def test_login_rate_limited_per_ip(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    for _ in range(5):
        assert (await other.post(f"{A}/login", json={"password": "wrong wrong"})).status_code == 401
    r = await other.post(f"{A}/login", json={"password": PW})  # even the right one is refused
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(r.headers["retry-after"]) <= 301
    # kiosk pairing has its own budget: a login lockout does not block it
    assert (await other.post(f"{A}/kiosk/code", json={"token": "x"})).status_code == 401


async def test_successful_logins_do_not_consume_the_budget(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    for _ in range(8):
        assert (await other.post(f"{A}/login", json={"password": PW})).status_code == 200


async def test_wrong_current_password_is_rate_limited(client: httpx.AsyncClient) -> None:
    await _set_pw(client)
    for _ in range(5):
        r = await client.put(
            f"{A}/password", json={"current": "wrong wrong", "new": "whatever pass"}
        )
        assert r.status_code == 403
    r = await client.put(f"{A}/password", json={"current": PW, "new": "whatever pass"})
    assert r.status_code == 429


# ---------------------------------------------------------------- kiosk
async def test_kiosk_token_file_created_at_startup(app: FastAPI, client: httpx.AsyncClient) -> None:
    f = app.state.auth.kiosk.path
    assert f.name == "kiosk-token" and f.read_text().endswith("\n")
    assert len(f.read_text().strip().splitlines()) == 1
    assert oct(f.stat().st_mode & 0o777) == "0o644"


async def test_kiosk_pairing_and_rotation(
    app: FastAPI, client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    token = app.state.auth.kiosk.read()
    assert (await other.post(f"{A}/kiosk/code", json={"token": token + "x"})).status_code == 401
    r = await _pair(other, token)
    assert r.status_code == 200 and r.json()["session_kind"] == "kiosk"
    assert (await other.get(PROTECTED)).status_code == 200
    assert (await other.post("/api/v1/kiosk/display", json={"on": True})).status_code == 200
    rows = (await client.get(f"{A}/sessions")).json()["sessions"]
    assert sorted(r["kind"] for r in rows) == ["browser", "kiosk"]
    # rotate: new token file, kiosk sessions revoked, the old token is dead
    r = await client.post(f"{A}/kiosk-token/rotate")
    assert r.status_code == 200 and r.json() == {"revoked": 1}
    assert (await other.get(PROTECTED)).status_code == 401
    new = app.state.auth.kiosk.read()
    assert new != token
    assert (await _pair(other, token)).status_code == 401
    assert (await _pair(other, new)).status_code == 200
    assert (await client.get(PROTECTED)).status_code == 200  # browsers are unaffected


async def test_kiosk_pairing_fails_closed_without_token_file(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.auth.kiosk.path.unlink()
    assert (await client.post(f"{A}/kiosk/code", json={"token": ""})).status_code == 401
    assert (await client.post(f"{A}/kiosk", json={"code": "x" * 40})).status_code == 401


async def test_kiosk_session_not_valid_after_password_set_to_other_browser_revocation(
    app: FastAPI, client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    """Changing the password signs out browsers but keeps the trusted kiosk."""
    await _pair(other, app.state.auth.kiosk.read())
    await _set_pw(client)
    assert (await other.get(PROTECTED)).status_code == 200
    assert (await other.get(f"{A}/status")).json()["session_kind"] == "kiosk"


# ---------------------------------------------------------------- origin guard
async def test_origin_guard_applies_to_cookie_requests(client: httpx.AsyncClient) -> None:
    await _set_pw(client)
    for method, url, body in (
        ("POST", f"{A}/login", {"password": PW}),
        ("POST", f"{A}/logout", None),
        ("PUT", f"{A}/password", {"current": PW, "new": "evil password"}),
        ("POST", f"{A}/sessions/revoke-all", None),
        ("POST", f"{A}/kiosk-token/rotate", None),
        ("POST", "/api/v1/camera/connect", None),
    ):
        r = await client.request(method, url, json=body, headers=EVIL)
        assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_ORIGIN", url
    assert (await client.get(PROTECTED, headers=EVIL)).status_code == 200  # reads are unaffected


# ---------------------------------------------------------------- websockets
@pytest.fixture
def tc(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _closed_code(ws: Any) -> int:
    with pytest.raises(WebSocketDisconnect) as ei:
        while True:
            ws.receive_text()
    return int(ei.value.code)


def test_ws_accepts_cookie_and_rejects_without(tc: TestClient) -> None:
    assert tc.put(f"{A}/password", json={"new": PW}).status_code == 200
    with tc.websocket_connect("/api/v1/ws/events") as ws:  # cookie jar of the TestClient
        assert ws.receive_json()["type"] == "camera_state"
    tc.cookies.clear()
    with tc.websocket_connect("/api/v1/ws/events") as ws:
        assert _closed_code(ws) == 4401
    tc.cookies.set(SESSION_COOKIE, "forged")
    with tc.websocket_connect("/api/v1/ws/liveview") as ws:
        assert _closed_code(ws) == 4401


def test_ws_api_key_subprotocol_still_works(tc: TestClient) -> None:
    key = tc.post("/api/v1/config/api-key").json()["api_key"]
    with tc.websocket_connect("/api/v1/ws/events", subprotocols=[f"apikey.{key}"]) as ws:
        assert ws.receive_json()["type"] == "camera_state"
    with tc.websocket_connect("/api/v1/ws/events", subprotocols=["apikey.nope"]) as ws:
        assert _closed_code(ws) == 4401


@pytest.mark.parametrize("path", ["/api/v1/ws/events", "/api/v1/ws/liveview"])
def test_ws_closed_4401_when_session_revoked(tc: TestClient, path: str) -> None:
    assert tc.put(f"{A}/password", json={"new": PW}).status_code == 200
    with tc.websocket_connect(path) as ws:
        ws.receive_text()  # snapshot / status
        tc.post(f"{A}/logout")
        assert _closed_code(ws) == 4401


@pytest.mark.parametrize("path", ["/api/v1/ws/events", "/api/v1/ws/liveview"])
def test_ws_closed_4401_when_open_app_becomes_protected(tc: TestClient, path: str) -> None:
    with tc.websocket_connect(path) as ws:
        ws.receive_text()
        other = TestClient(tc.app)  # a different browser sets the first password
        assert other.put(f"{A}/password", json={"new": PW}).status_code == 200
        assert _closed_code(ws) == 4401


def test_ws_cookie_socket_survives_password_change_by_same_session(tc: TestClient) -> None:
    tc.put(f"{A}/password", json={"new": PW})
    with tc.websocket_connect("/api/v1/ws/events") as ws:
        ws.receive_text()
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ws_cross_origin_with_cookie_still_rejected(tc: TestClient) -> None:
    tc.put(f"{A}/password", json={"new": PW})
    with (
        pytest.raises(WebSocketDisconnect) as ei,
        tc.websocket_connect("/api/v1/ws/events", headers=EVIL),
    ):
        pass
    assert ei.value.code == 4403


# ---------------------------------------------------------------- openapi
async def test_openapi_declares_cookie_scheme(app: FastAPI) -> None:
    schemes = app.openapi()["components"]["securitySchemes"]
    assert {"APIKeyHeader", "APIKeyCookie"} <= set(schemes)
    assert schemes["APIKeyCookie"] == {"type": "apiKey", "in": "cookie", "name": SESSION_COOKIE}


async def test_no_secret_in_logs(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture, app: FastAPI
) -> None:
    caplog.set_level("DEBUG")
    await _set_pw(client)
    token = client.cookies[SESSION_COOKIE]
    await client.post(f"{A}/login", json={"password": "wrong wrong"})
    await client.post(f"{A}/kiosk", json={"token": app.state.auth.kiosk.read()})
    text = caplog.text
    assert PW not in text and token not in text and app.state.auth.kiosk.read() not in text


async def test_kiosk_code_is_single_use_and_expires(
    app: FastAPI,
    client: httpx.AsyncClient,
    other: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_pw(client)
    token = app.state.auth.kiosk.read()
    code = (await other.post(f"{A}/kiosk/code", json={"token": token})).json()["code"]
    assert (await other.post(f"{A}/kiosk", json={"code": code})).status_code == 200
    assert (await other.post(f"{A}/kiosk", json={"code": code})).status_code == 401  # used
    assert (await other.post(f"{A}/kiosk", json={"token": token})).status_code == 422  # raw token
    code = (await other.post(f"{A}/kiosk/code", json={"token": token})).json()["code"]
    real = app.state.auth.kiosk_codes._clock
    monkeypatch.setattr(app.state.auth.kiosk_codes, "_clock", lambda: real() + 31)
    assert (await other.post(f"{A}/kiosk", json={"code": code})).status_code == 401


async def test_kiosk_pairing_has_its_own_limiter(
    app: FastAPI, client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    for _ in range(5):
        assert (await other.post(f"{A}/kiosk/code", json={"token": "bad"})).status_code == 401
    assert (await other.post(f"{A}/kiosk/code", json={"token": "bad"})).status_code == 429
    assert (await other.post(f"{A}/kiosk", json={"code": "x"})).status_code == 429
    # the login budget is untouched
    assert (await other.post(f"{A}/login", json={"password": PW})).status_code == 200


async def test_secure_cookie_always_setting(
    app: FastAPI, client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    await _set_pw(client)
    r = await other.post(f"{A}/login", json={"password": PW})
    assert "secure" not in r.headers["set-cookie"].lower()  # auto + http
    app.state.config_store.update({"security": {"secure_cookie": "always"}})
    r = await other.post(f"{A}/login", json={"password": PW})
    assert "secure" in r.headers["set-cookie"].lower()
