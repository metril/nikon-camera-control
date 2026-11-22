import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed
from backend.services.timelapse import runner as runner_mod

T = "/api/v1/timelapse"
DONE = {"completed", "stopped", "failed"}


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "SETTLE_S", 0.0)


def body(**kw: Any) -> dict[str, Any]:
    return {"name": "Sky", "interval_s": 0.2, "total_frames": 3} | kw


async def status(c: httpx.AsyncClient) -> dict[str, Any]:
    r = await c.get(T)
    assert r.status_code == 200
    return r.json()


async def wait_for(c: httpx.AsyncClient, states: set[str], limit: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + limit
    while True:
        st = await status(c)
        if st["state"] in states:
            return st
        assert time.monotonic() < deadline, st
        await asyncio.sleep(0.01)


async def frames_at_least(c: httpx.AsyncClient, n: int) -> None:
    deadline = time.monotonic() + 10
    while (await status(c))["counters"]["frames_done"] < n:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)


async def put(c: httpx.AsyncClient, **kw: Any) -> httpx.Response:
    return await c.put(f"{T}/config", json=body(**kw))


async def test_operation_ids_and_routes(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    ops = {
        (m, p): o["operationId"] for p, v in paths.items() if p.startswith(T) for m, o in v.items()
    }
    assert ops == {
        ("get", T): "get_timelapse_status",
        ("put", f"{T}/config"): "set_timelapse_config",
        ("get", f"{T}/preview"): "preview_timelapse",
        ("get", f"{T}/presets"): "list_timelapse_presets",
        ("post", f"{T}/start"): "start_timelapse",
        ("post", f"{T}/pause"): "pause_timelapse",
        ("post", f"{T}/resume"): "resume_timelapse",
        ("post", f"{T}/stop"): "stop_timelapse",
    }
    schemas = app.openapi()["components"]["schemas"]
    assert {"TimelapseStatus", "TimelapseSetup", "TimelapseConfigResult"} <= set(schemas)


async def test_idle_status_presets_and_preview_without_config(client: httpx.AsyncClient) -> None:
    st = await status(client)
    assert st["state"] == "idle" and st["session_id"] is None and st["config"] is None
    assert set(st["counters"].values()) == {0} and len(st["counters"]) == 5
    presets = (await client.get(f"{T}/presets")).json()["items"]
    assert {p["name"] for p in presets} >= {"exposure_3", "hdr_3shot", "aperture_sweep"}
    assert all(len(p["steps"]) >= 2 for p in presets)
    r = await client.get(f"{T}/preview")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    for action in ("start", "pause", "resume", "stop"):
        assert (await client.post(f"{T}/{action}")).status_code == 409


async def test_config_returns_normalised_steps_and_estimate(
    connected_client: httpx.AsyncClient,
) -> None:
    r = await put(
        connected_client,
        interval_s=20,
        bracketing={
            "mode": "quick",
            "iso": ["100", "200"],
            "aperture": ["f/4", "f/8"],
            "combine_mode": "paired",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert [s["settings"] for s in out["resolved_steps"]] == [
        {"iso": "100", "f-number": "f/4"},
        {"iso": "200", "f-number": "f/8"},
    ]
    assert out["estimate"]["total_shots"] == 6 and out["estimate"]["disk_bytes"] > 0
    assert out["min_interval_s"] > 1
    assert (await connected_client.get(f"{T}/preview")).json() == out
    st = await status(connected_client)
    assert st["state"] == "configured" and st["config"]["name"] == "Sky"
    assert st["counters"]["frames_planned"] == 6


async def test_config_validation_errors(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    r = await put(c, interval_s=2, bracketing={"mode": "preset", "preset": "exposure_5"})
    assert r.status_code == 422 and r.json()["error"]["details"]["min_interval_s"] > 5
    assert "minimum" in r.json()["error"]["message"]
    r = await put(c, interval_s=20, bracketing={"mode": "quick", "iso": ["100", "999"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SETTING_INVALID"
    r = await put(c, interval_s=20, bracketing={"mode": "preset", "preset": "nope"})
    assert r.status_code == 422
    r = await put(c, duration_s=100)  # both frames and duration
    assert r.status_code == 422
    r = await put(c, total_frames=None)
    assert r.status_code == 422
    r = await put(c, total_frames=None, duration_s=10**7)
    assert r.status_code == 422 and "maximum" in r.json()["error"]["message"]
    r = await put(c, bracketing={"mode": "steps", "steps": [{"settings": {}}, {"settings": {}}]})
    assert r.status_code == 422
    r = await put(c, bracketing={"mode": "steps", "steps": [{"settings": {"iso": "100"}}]})
    assert r.status_code == 422
    r = await put(
        c,
        interval_s=20,
        bracketing={
            "mode": "steps",
            "steps": [{"settings": {"iso": "100"}}, {"settings": {"batterylevel": "1"}}],
        },
    )
    assert r.status_code in (403, 422)
    assert (await status(c))["state"] == "idle"


async def test_config_accepted_without_camera_and_start_needs_camera(
    client: httpx.AsyncClient,
) -> None:
    assert (await put(client)).status_code == 200
    r = await client.post(f"{T}/start")
    assert r.status_code == 503 and r.json()["error"]["code"] == "CAMERA_NOT_CONNECTED"
    assert (await status(client))["state"] == "configured"


async def test_full_lifecycle_writes_session(
    connected_client: httpx.AsyncClient, app: FastAPI
) -> None:
    c = connected_client
    await put(c, total_frames=4)
    r = await c.post(f"{T}/start")
    assert r.status_code == 200 and r.json()["state"] == "running" and r.json()["session_id"]
    st = await wait_for(c, DONE)
    assert st["state"] == "completed" and st["counters"]["frames_done"] == 4
    assert len(st["last_frame"]["files"]) == 1 and st["timing"]["elapsed_s"] > 0
    sid = st["session_id"]
    s = (await c.get(f"/api/v1/sessions/{sid}")).json()
    assert s["status"] == "completed" and s["frames_captured"] == 4 and s["name"] == "Sky"
    frames = (await c.get(f"/api/v1/sessions/{sid}/frames")).json()
    assert frames["total"] == 4 and frames["items"][0]["files"][0]["kind"] == "jpeg"
    assert (await c.get("/api/v1/camera")).json()["leased_by"] is None
    assert (await c.post(f"{T}/start")).status_code == 200  # restart from completed -> new session
    st2 = await wait_for(c, DONE)
    assert st2["session_id"] != sid


async def test_outside_capture_and_settings_get_409_during_run_regression(
    connected_client: httpx.AsyncClient,
) -> None:
    c = connected_client
    await put(c, total_frames=100)
    await c.post(f"{T}/start")
    for _ in range(3):
        r = await c.post("/api/v1/capture", json={})
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
    r = await c.patch("/api/v1/settings", json={"values": {"iso": "800"}})
    assert r.status_code == 409, r.text
    assert (await c.get("/api/v1/camera")).json()["leased_by"] == "timelapse"
    assert (await put(c)).status_code == 409  # no reconfigure while running
    assert (await c.post(f"{T}/stop")).json()["state"] == "stopped"
    assert (await c.post("/api/v1/capture", json={})).status_code == 200  # lease released


async def test_pause_resume_stop_endpoints(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    await put(c, total_frames=1000)
    await c.post(f"{T}/start")
    r = await c.post(f"{T}/pause")
    assert r.json()["state"] == "paused" and r.json()["paused_reason"] == "user"
    assert (await c.post(f"{T}/pause")).status_code == 409
    assert (await c.post(f"{T}/start")).status_code == 409  # not while paused
    await asyncio.sleep(0.1)
    n = (await status(c))["counters"]["frames_done"]
    await asyncio.sleep(0.3)
    assert (await status(c))["counters"]["frames_done"] == n  # nothing while paused
    assert (await c.post(f"{T}/resume")).json()["state"] == "running"
    await asyncio.sleep(0.4)
    assert (await status(c))["counters"]["frames_done"] > n
    assert (await c.post(f"{T}/stop")).json()["state"] == "stopped"
    sid = (await status(c))["session_id"]
    assert (await c.get(f"/api/v1/sessions/{sid}")).json()["status"] == "stopped"
    assert (await c.post(f"{T}/stop")).status_code == 409


async def test_duration_deadline_via_api(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    await put(c, total_frames=None, duration_s=1, interval_s=0.25)
    t0 = time.monotonic()
    await c.post(f"{T}/start")
    st = await wait_for(c, DONE)
    assert st["state"] == "completed" and 3 <= st["counters"]["frames_done"] <= 4
    assert time.monotonic() - t0 < 3


async def test_failure_budget_via_api_regression(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    fake_camera.fail_next("capture", 100, CameraOperationFailed())
    await put(c, total_frames=1000, interval_s=0.1)
    await c.post(f"{T}/start")
    st = await wait_for(c, DONE)
    assert st["state"] == "failed" and st["counters"]["failures"] == 5
    assert "5 consecutive" in st["error"]
    assert (await c.get("/api/v1/camera")).json()["leased_by"] is None
    sid = st["session_id"]
    assert (await c.get(f"/api/v1/sessions/{sid}")).json()["status"] == "failed"


async def test_card_full_ends_run_immediately(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    fake_camera.card_full()
    await put(c, total_frames=50, interval_s=0.1)
    await c.post(f"{T}/start")
    st = await wait_for(c, DONE)
    assert st["state"] == "failed" and "Storage full" in st["error"]
    assert fake_camera.calls["capture"] == 1


async def test_unplug_replug_pauses_then_resumes(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    await put(c, total_frames=1000, interval_s=0.1)
    await c.post(f"{T}/start")
    await frames_at_least(c, 2)
    fake_camera.unplug()
    st = await wait_for(c, {"paused"})
    assert st["paused_reason"] == "camera_disconnected"
    fake_camera.replug()
    assert (await c.post("/api/v1/camera/connect")).status_code == 200
    st = await wait_for(c, {"running"})
    n = st["counters"]["frames_done"]
    await frames_at_least(c, n + 2)
    await c.post(f"{T}/stop")
    assert (await c.get("/api/v1/camera")).json()["leased_by"] is None


async def test_bracket_run_restores_camera_settings_regression(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    cam = app.state.camera_service
    await cam.set_setting("iso", "800")
    await cam.set_setting("exposurecompensation", "+1")
    before = {n: (await cam.get_setting(n)).value for n in ("iso", "exposurecompensation")}
    r = await put(
        c, total_frames=1, interval_s=10, bracketing={"mode": "preset", "preset": "hdr_iso_combo"}
    )
    assert r.status_code == 200 and r.json()["estimate"]["total_shots"] == 4
    await c.post(f"{T}/start")
    st = await wait_for(c, DONE)
    assert st["state"] == "completed" and st["counters"]["frames_done"] == 4
    after = {n: (await cam.get_setting(n)).value for n in ("iso", "exposurecompensation")}
    assert after == before == {"iso": "800", "exposurecompensation": "+1"}
    frames = (await c.get(f"/api/v1/sessions/{st['session_id']}/frames")).json()["items"]
    assert [f["bracket"]["step_index"] for f in frames] == [0, 1, 2, 3]
    assert {f["set_index"] for f in frames} == {0}
    assert frames[3]["bracket"]["settings"] == {"exposurecompensation": "0", "iso": "800"}


async def test_restart_shows_interrupted_session_and_idle_status(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any, config_store: Any
) -> None:
    from backend.app import create_app

    c = connected_client
    await put(c, total_frames=1000, interval_s=0.1)
    await c.post(f"{T}/start")
    await frames_at_least(c, 2)
    sid = (await status(c))["session_id"]
    # "crash": a second app process starts on the same output dir while the first is mid-run
    app2 = create_app(
        config_store=config_store,
        data_dir=tmp_dirs.data_dir,
        output_dir=tmp_dirs.output_dir,
        backend_factory=lambda: FakeCamera(),
        auto_connect=False,
        event_quiet_window_s=0.02,
    )
    async with app2.router.lifespan_context(app2):
        transport = httpx.ASGITransport(app=app2, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c2:
            assert (await c2.get(T)).json()["state"] == "idle"
            s = (await c2.get(f"/api/v1/sessions/{sid}")).json()
            assert s["status"] == "interrupted" and s["frames_captured"] >= 2
    await c.post(f"{T}/stop")
