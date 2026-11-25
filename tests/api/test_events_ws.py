import pytest
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from backend.core.security import hash_api_key

W = "/api/v1/ws/events"


def test_snapshot_then_events(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(W) as ws:
        snap = ws.receive_json()
        assert snap["type"] == "camera_state" and snap["data"]["state"] == "disconnected"
        assert "ts" in snap
        assert ws_client.post("/api/v1/camera/connect").status_code == 200
        seen = []
        while "camera_connected" not in seen:
            seen.append(ws.receive_json()["type"])
        assert "camera_state" in seen


def test_ping_pong(ws_client: TestClient) -> None:
    with ws_client.websocket_connect(W) as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_text("not json")
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_auth(ws_client: TestClient) -> None:
    store = ws_client.app.state.config_store  # type: ignore[attr-defined]
    store.set_api_key_hash(hash_api_key("k1"))
    # accepted first, then closed with 4401 (not an HTTP 403 at handshake)
    with ws_client.websocket_connect(W) as ws, pytest.raises(WebSocketDisconnect) as ei:
        ws.receive_json()
    assert ei.value.code == 4401
    with (
        ws_client.websocket_connect(W, subprotocols=["apikey.bad"]) as ws,
        pytest.raises(WebSocketDisconnect) as ei,
    ):
        ws.receive_json()
    assert ei.value.code == 4401
    # the query-string fallback is gone
    with ws_client.websocket_connect(f"{W}?api_key=k1") as ws, pytest.raises(WebSocketDisconnect):
        ws.receive_json()
    with ws_client.websocket_connect(W, subprotocols=["apikey.k1"]) as ws:
        assert ws.accepted_subprotocol == "apikey.k1"
        assert ws.receive_json()["type"] == "camera_state"


def test_subscription_closed_on_disconnect(ws_client: TestClient) -> None:
    bus = ws_client.app.state.event_bus  # type: ignore[attr-defined]
    with ws_client.websocket_connect(W) as ws:
        ws.receive_json()
        assert bus.subscriber_count == 1
    ws_client.get("/api/v1/health")  # let the loop run the handler cleanup
    for _ in range(100):
        if bus.subscriber_count == 0:
            break
        import time

        time.sleep(0.02)
    assert bus.subscriber_count == 0


def test_slow_subscriber_closed_1013(ws_client: TestClient) -> None:
    bus = ws_client.app.state.event_bus  # type: ignore[attr-defined]
    with ws_client.websocket_connect(W) as ws:
        ws.receive_json()

        # flood from inside the loop so the writer cannot drain between publishes
        async def flood() -> None:
            for _ in range(1000):
                bus.publish("error", {})

        ws_client.portal.call(flood)  # type: ignore[union-attr]
        with pytest.raises(WebSocketDisconnect) as ei:
            for _ in range(2000):
                ws.receive_json()
        assert ei.value.code == 1013


@pytest.mark.parametrize("path", ["/api/v1/ws/events", "/api/v1/ws/liveview"])
def test_socket_closed_4401_when_key_rotated(ws_client: TestClient, path: str) -> None:
    store = ws_client.app.state.config_store  # type: ignore[attr-defined]
    store.set_api_key_hash(hash_api_key("k1"))
    with ws_client.websocket_connect(path, subprotocols=["apikey.k1"]) as ws:
        ws.receive_json()
        store.set_api_key_hash(hash_api_key("k2"))
        assert _closed_code(ws) == 4401


@pytest.mark.parametrize("path", ["/api/v1/ws/events", "/api/v1/ws/liveview"])
def test_open_socket_closed_4401_when_key_first_created(ws_client: TestClient, path: str) -> None:
    with ws_client.websocket_connect(path) as ws:
        ws.receive_json()
        assert ws_client.post("/api/v1/config/api-key").status_code == 200
        assert _closed_code(ws) == 4401


def _closed_code(ws: WebSocketTestSession) -> int | None:
    for _ in range(20):
        msg = ws.receive()
        if msg["type"] == "websocket.close":
            return int(msg["code"])
    return None


@pytest.mark.parametrize("module", ["backend.api.v1.events_ws", "backend.api.v1.liveview"])
async def test_keywatch_closed_when_accept_fails(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    mod = importlib.import_module(module)
    closed: list[bool] = []

    class FakeWatch:
        def __init__(self, _ws: object) -> None:
            pass

        def close(self) -> None:
            closed.append(True)

    class BrokenSocket:
        scope = {"subprotocols": []}

        async def accept(self, **_kw: object) -> None:
            raise RuntimeError("client went away")

    async def ok(_ws: object) -> bool:
        return True

    monkeypatch.setattr(mod, "KeyWatch", FakeWatch)
    monkeypatch.setattr(mod, "ws_authorize", ok)
    handler = mod.events_ws if module.endswith("events_ws") else mod.liveview_ws
    with pytest.raises(RuntimeError):
        await handler(BrokenSocket())
    assert closed == [True]
