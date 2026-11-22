from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.camera.fake import FakeCamera
from backend.core.security import hash_api_key

W = "/api/v1/ws/liveview"
API = "/api/v1/liveview"


def wait(pred: Callable[[], bool], timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


def recv(ws: Any) -> tuple[str, Any]:
    msg = ws.receive()
    if msg.get("bytes") is not None:
        return "frame", msg["bytes"]
    import json

    return "text", json.loads(msg["text"])


def frames(ws: Any, n: int) -> list[bytes]:
    out: list[bytes] = []
    while len(out) < n:
        kind, v = recv(ws)
        if kind == "frame":
            out.append(v)
    return out


def state(c: TestClient) -> str:
    return str(c.get("/api/v1/camera").json()["state"])


@pytest.fixture
def lv(ws_client: TestClient) -> TestClient:
    ws_client.app.state.config_store.update({"liveview": {"target_fps": 30}})  # type: ignore[attr-defined]
    assert ws_client.post("/api/v1/camera/connect").status_code == 200
    return ws_client


def test_two_clients_share_one_producer(lv: TestClient, fake_camera: FakeCamera) -> None:
    with lv.websocket_connect(W) as a, lv.websocket_connect(W) as b:
        fa, fb = frames(a, 5), frames(b, 5)
        assert len(set(fa) & set(fb)) >= 2  # same frames reach both clients
        st = lv.get(API).json()
        assert st["subscribers"] == 2
        assert fake_camera.calls["capture_preview"] <= st["frames_produced"] + 1  # not doubled


def test_last_client_leaving_returns_to_idle(lv: TestClient) -> None:
    with lv.websocket_connect(W) as ws:
        frames(ws, 1)
        assert state(lv) == "liveview"
    wait(lambda: state(lv) == "idle" and not lv.get(API).json()["running"])


def test_sticky_start_survives_client_leaving(lv: TestClient) -> None:
    assert lv.post(f"{API}/start").json()["sticky"] is True
    with lv.websocket_connect(W) as ws:
        frames(ws, 1)
    time.sleep(0.1)
    assert state(lv) == "liveview" and lv.get(API).json()["running"]
    st = lv.post(f"{API}/stop").json()
    assert st["running"] is False
    wait(lambda: state(lv) == "idle")


def test_capture_during_live_view_resumes_stream(lv: TestClient) -> None:
    with lv.websocket_connect(W) as ws:
        frames(ws, 2)
        svc = lv.app.state.camera_service  # type: ignore[attr-defined]
        assert lv.portal.call(svc.capture)  # type: ignore[union-attr]
        wait(lambda: state(lv) == "liveview")
        frames(ws, 3)


def test_unplug_goes_inactive_and_replug_resumes(lv: TestClient, fake_camera: FakeCamera) -> None:
    with lv.websocket_connect(W) as ws:
        frames(ws, 1)
        fake_camera.unplug()
        wait(lambda: not lv.get(API).json()["active"])
        assert lv.get(API).json()["running"]
        fake_camera.replug()
        lv.post("/api/v1/camera/connect")
        wait(lambda: lv.get(API).json()["active"])
        frames(ws, 2)


def test_ws_open_without_camera_then_frames_when_it_connects(ws_client: TestClient) -> None:
    """Regression: old behaviour closed 1003 when the camera was missing."""
    with ws_client.websocket_connect(W) as ws:
        kind, msg = recv(ws)
        assert kind == "text" and msg["type"] == "status"
        assert msg["active"] is False and msg["reason"] == "camera_disconnected"
        ws_client.post("/api/v1/camera/connect")
        frames(ws, 2)


def test_ping_status_and_no_client_message_dropped(lv: TestClient) -> None:
    """Regression: receive_json under wait_for(0.001) dropped client messages."""
    with lv.websocket_connect(W) as ws:
        for _ in range(20):
            ws.send_json({"type": "ping"})
        ws.send_json({"type": "status"})
        ws.send_text("garbage")
        pongs, statuses = 0, 0
        while pongs < 20 or statuses < 2:  # 1 on connect + 1 requested
            kind, v = recv(ws)
            if kind == "text":
                pongs += v["type"] == "pong"
                statuses += v["type"] == "status"


def test_slow_client_does_not_block_fast_one(lv: TestClient) -> None:
    with lv.websocket_connect(W) as slow, lv.websocket_connect(W) as fast:
        frames(fast, 10)  # slow never reads
        st = lv.get(API).json()
        assert st["frames_dropped"] > 0 or st["frames_sent"] >= 10
        frames(slow, 1)


def test_snapshot_when_idle_restores_state(lv: TestClient) -> None:
    r = lv.get(f"{API}/snapshot")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:3] == b"\xff\xd8\xff"
    wait(lambda: state(lv) == "idle")
    assert lv.get(API).json()["running"] is False


def test_snapshot_while_streaming(lv: TestClient) -> None:
    lv.post(f"{API}/start")
    r = lv.get(f"{API}/snapshot")
    assert r.content[:3] == b"\xff\xd8\xff" and state(lv) == "liveview"


def test_snapshot_without_camera_is_503(ws_client: TestClient) -> None:
    assert ws_client.get(f"{API}/snapshot").status_code == 503


def test_openapi_operation_ids(ws_client: TestClient) -> None:
    paths = ws_client.app.openapi()["paths"]  # type: ignore[attr-defined]
    assert paths[API]["get"]["operationId"] == "get_liveview"
    assert paths[f"{API}/start"]["post"]["operationId"] == "start_liveview"
    assert paths[f"{API}/stop"]["post"]["operationId"] == "stop_liveview"
    assert paths[f"{API}/snapshot"]["get"]["operationId"] == "get_liveview_snapshot"


def test_auth_required_on_ws_and_rest(ws_client: TestClient) -> None:
    ws_client.app.state.config_store.set_api_key_hash(hash_api_key("k1"))  # type: ignore[attr-defined]
    with ws_client.websocket_connect(W) as ws, pytest.raises(WebSocketDisconnect) as ei:
        ws.receive_json()
    assert ei.value.code == 4401
    assert ws_client.get(API).status_code == 401
    with ws_client.websocket_connect(W, subprotocols=["apikey.k1"]) as ws:
        assert ws.receive_json()["type"] == "status"
