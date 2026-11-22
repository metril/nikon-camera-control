import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

U = "/api/v1/camera/connect"
EVIL = {"Origin": "http://evil.example"}


async def test_cross_origin_post_rejected_with_envelope(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/config/api-key", headers=EVIL)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN_ORIGIN"
    assert r.json()["error"]["request_id"]
    for m in ("put", "patch", "delete"):
        assert (await client.request(m, "/api/v1/config", headers=EVIL)).status_code == 403
    assert (await client.get("/api/v1/config")).json()["api_key_set"] is False


async def test_same_origin_and_no_origin_allowed(client: httpx.AsyncClient) -> None:
    same = await client.post(U, headers={"Origin": "https://t"})  # scheme-insensitive
    assert same.status_code != 403
    assert (await client.post(U)).status_code != 403
    assert (await client.post(U, headers={"Origin": "http://t:9999"})).status_code == 403
    assert (await client.post(U, headers={"Origin": "null"})).status_code == 403


async def test_get_unaffected_by_origin(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/health", headers=EVIL)).status_code == 200


async def test_origin_listed_in_cors_origins_allowed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.config_store.update({"cors_origins": ["http://good.example"]})  # live, no restart
    ok = await client.post(U, headers={"Origin": "http://good.example"})
    assert ok.status_code != 403
    assert (await client.post(U, headers=EVIL)).status_code == 403


def test_cross_origin_websocket_rejected(ws_client: TestClient) -> None:
    for url in ("/api/v1/ws/events", "/api/v1/ws/liveview"):
        with (
            pytest.raises(WebSocketDisconnect) as ei,
            ws_client.websocket_connect(url, headers=EVIL),
        ):
            pass
        assert ei.value.code == 4403
        with ws_client.websocket_connect(url, headers={"Origin": "http://testserver"}):
            pass
        with ws_client.websocket_connect(url):  # no Origin
            pass
