import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from backend.api.schemas.common import EventType
from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed
from backend.core.state import CameraState
from backend.services.focus import FocusService

F = "/api/v1/focus"


def install(app: FastAPI, sleeps: list[float] | None = None) -> FocusService:
    """Register a FocusService with a virtual settle sleep before any request."""
    from backend.api.v1.capture import build_capture_service

    async def sleep(s: float) -> None:
        if sleeps is not None:
            sleeps.append(s)
        await asyncio.sleep(0)

    st = app.state
    return st.services.get(
        "focus",
        lambda: FocusService(
            st.camera_service,
            st.services.get("capture", lambda: build_capture_service(st)),
            st.job_manager,
            st.storage,
            sleep=sleep,
            default_prefix=lambda: st.config_store.config.camera.filename_prefix,
        ),
    )


async def wait_job(c: httpx.AsyncClient, jid: str, limit: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + limit
    while True:
        j = (await c.get(f"/api/v1/jobs/{jid}")).json()
        if j["status"] in ("completed", "failed", "cancelled"):
            return j
        assert time.monotonic() < deadline, j
        await asyncio.sleep(0.01)


STACK = {"steps_per_shot": 10, "shots": 4, "settle_ms": 100, "name": "My Bug/../x"}


async def test_routes(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    ops = {
        (m, p): o["operationId"] for p, v in paths.items() if p.startswith(F) for m, o in v.items()
    }
    assert ops == {
        ("get", F): "get_focus",
        ("post", f"{F}/af"): "autofocus",
        ("post", f"{F}/mf"): "manual_focus",
        ("post", f"{F}/point"): "set_af_point",
        ("post", f"{F}/reset"): "reset_focus_position",
        ("post", f"{F}/stack"): "start_focus_stack",
    }


async def test_disconnected_is_503(client: httpx.AsyncClient) -> None:
    assert (await client.post(f"{F}/af")).status_code == 503
    assert (await client.post(f"{F}/mf", json={"steps": 5})).status_code == 503


async def test_af_happy_path(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    r = await c.post(f"{F}/af")
    assert r.status_code == 200 and r.json() == {"ok": True, "focused": True}
    assert (await c.get(F)).json()["last_af_at"] is not None


async def test_af_failure_keeps_camera_connected(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    fake_camera.fail_next("set_config", exc=CameraOperationFailed("Out of focus"))
    r = await connected_client.post(f"{F}/af")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "CAMERA_OPERATION_FAILED"
    assert app.state.camera_service.status().connected
    assert (await connected_client.get(F)).json()["last_af_at"] is None


async def test_mf_accumulates_and_restores_liveview(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    assert not fake_camera.viewfinder_on
    r = await c.post(f"{F}/mf", json={"steps": 30})
    assert r.json() == {"ok": True, "steps": 30, "relative_position": 30}
    assert not fake_camera.viewfinder_on and app.state.camera_service.state == "idle"
    r = await c.post(f"{F}/mf", json={"steps": -50})
    assert r.json()["relative_position"] == -20
    g = (await c.get(F)).json()
    assert g["relative_position"] == -20 and g["liveview_required"] is True
    assert g["range"] == {"min": -1000, "max": 1000, "step": 1}
    assert (await c.post(f"{F}/reset")).json()["relative_position"] == 0
    assert (await c.get(F)).json()["relative_position"] == 0


async def test_mf_in_liveview_stays_in_liveview(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    from backend.core.state import CameraState

    await app.state.camera_service.transition(CameraState.LIVEVIEW)
    assert (await connected_client.post(f"{F}/mf", json={"steps": 5})).status_code == 200
    assert fake_camera.viewfinder_on and app.state.camera_service.state == "liveview"


async def test_mf_validation(connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    assert (await c.post(f"{F}/mf", json={"steps": 0})).status_code == 422
    r = await c.post(f"{F}/mf", json={"steps": 5000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SETTING_INVALID"
    assert (await c.get(F)).json()["relative_position"] == 0


async def test_stack_happy_path(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera, tmp_dirs: Any
) -> None:
    sleeps: list[float] = []
    svc = install(app, sleeps)
    r = await connected_client.post(f"{F}/stack", json=STACK)
    assert r.status_code == 202 and r.json()["kind"] == "focus-stack"
    j = await wait_job(connected_client, r.json()["id"])
    assert j["status"] == "completed", j
    res = j["result"]
    folder = Path(tmp_dirs.output_dir) / res["folder"]
    assert res["folder"].startswith("stacks/") and ".." not in res["folder"]
    assert len(list(folder.iterdir())) == res["file_count"] >= 4
    assert res["total_steps_moved"] == 30 and res["net_steps"] == 0 and res["returned_to_start"]
    assert svc.relative_position == 0
    assert sleeps == [0.1] * 3
    st = app.state.camera_service.status()
    assert st.leased_by is None and st.state == "idle" and not fake_camera.viewfinder_on


async def test_stack_filename_prefix(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    install(app)
    body = STACK | {"filename_prefix": "my bug!"}
    r = await connected_client.post(f"{F}/stack", json=body)
    j = await wait_job(connected_client, r.json()["id"])
    assert j["status"] == "completed", j
    names = [p.name for p in (Path(tmp_dirs.output_dir) / j["result"]["folder"]).iterdir()]
    assert names and all(n.startswith("my-bug-") for n in names)
    assert any(n.startswith("my-bug-001-") for n in names)


async def test_stack_default_prefix_from_config(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_dirs: Any
) -> None:
    install(app)
    await connected_client.patch("/api/v1/config", json={"camera": {"filename_prefix": "cfg"}})
    r = await connected_client.post(f"{F}/stack", json=STACK)
    j = await wait_job(connected_client, r.json()["id"])
    assert j["status"] == "completed", j
    names = [p.name for p in (Path(tmp_dirs.output_dir) / j["result"]["folder"]).iterdir()]
    assert names and all(n.startswith("cfg-001-") or n.startswith("cfg-0") for n in names)


async def test_stack_far_to_near_no_return(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    svc = install(app)
    body = STACK | {"direction": "far_to_near", "return_to_start": False, "shots": 3}
    j = await wait_job(
        connected_client, (await connected_client.post(f"{F}/stack", json=body)).json()["id"]
    )
    assert j["result"]["net_steps"] == -20 and svc.relative_position == -20


async def test_stack_cancel_releases_lease_and_returns_focus(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    svc = install(app)
    gate = asyncio.Event()

    async def slow(_: float) -> None:
        gate.set()
        await asyncio.sleep(30)

    svc._sleep = slow
    jid = (await c.post(f"{F}/stack", json=STACK)).json()["id"]
    await gate.wait()
    assert svc.relative_position == 10
    assert (await c.delete(f"/api/v1/jobs/{jid}")).status_code == 200
    j = await wait_job(c, jid)
    assert j["status"] == "cancelled"
    assert svc.relative_position == 0
    assert app.state.camera_service.status().leased_by is None


async def test_stack_capture_failure_fails_cleanly(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = install(app)
    c = connected_client
    reached, release = asyncio.Event(), asyncio.Event()

    async def gated(_: float) -> None:
        reached.set()
        await release.wait()

    svc._sleep = gated
    jid = (await c.post(f"{F}/stack", json=STACK)).json()["id"]
    await reached.wait()
    fake_camera.fail_next("capture", exc=CameraOperationFailed("nope"))
    release.set()
    j = await wait_job(c, jid)
    assert j["status"] == "failed" and j["error_code"] == "CAMERA_OPERATION_FAILED"
    assert svc.relative_position == 0
    assert app.state.camera_service.status().leased_by is None


async def test_stack_refused_during_other_lease(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    async with app.state.camera_service.lease("timelapse"):
        r = await connected_client.post(f"{F}/stack", json=STACK)
        assert r.status_code == 409
        assert (await connected_client.post(f"{F}/mf", json={"steps": 5})).status_code == 409
        assert (await connected_client.get(F)).status_code == 200


async def test_stack_exclusive_conflict(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    svc = install(app)
    svc._sleep = lambda _: asyncio.sleep(30)
    c = connected_client
    jid = (await c.post(f"{F}/stack", json=STACK)).json()["id"]
    r = await c.post(f"{F}/stack", json=STACK)
    assert r.status_code == 409
    await c.delete(f"/api/v1/jobs/{jid}")
    await wait_job(c, jid)


async def test_stack_body_validation(connected_client: httpx.AsyncClient) -> None:
    for bad in ({"shots": 1}, {"shots": 201}, {"steps_per_shot": 0}, {"direction": "x"}):
        r = await connected_client.post(f"{F}/stack", json=STACK | bad)
        assert r.status_code == 422


async def test_stack_step_outside_drive_range_refused_at_request_time(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    svc = install(app)
    r = await connected_client.post(f"{F}/stack", json=STACK | {"steps_per_shot": 2000})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SETTING_INVALID"
    assert app.state.camera_service.status().leased_by is None
    assert svc.relative_position == 0
    assert (await connected_client.get("/api/v1/jobs")).json() == []
    assert (
        await connected_client.post(f"{F}/stack", json=STACK | {"steps_per_shot": 40_000})
    ).status_code == 422  # schema cap


async def test_stack_holds_lease_from_request_so_second_exposure_job_gets_409(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    svc = install(app)
    svc._sleep = lambda _: asyncio.sleep(30)
    jid = (await c.post(f"{F}/stack", json=STACK)).json()["id"]
    assert app.state.camera_service.status().leased_by == "focus-stack"
    r = await c.post("/api/v1/capture/bulb", json={"seconds": 2})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
    await c.delete(f"/api/v1/jobs/{jid}")
    await wait_job(c, jid)
    assert app.state.camera_service.status().leased_by is None


async def test_cancel_during_move_still_counts_the_drive_that_ran(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = install(app)
    fake_camera.set_latency("set_config", 0.15)
    t = asyncio.create_task(svc.move(10))
    deadline = time.monotonic() + 5
    while fake_camera.calls.get("set_config", 0) < 1:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.005)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    assert svc.relative_position == 10  # drive completed on the camera and is accounted
    assert app.state.camera_service.state == "idle"


async def test_failed_move_leaves_position_unchanged(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = install(app)
    fake_camera.fail_next("set_config", 2, CameraOperationFailed("busy"))
    r = await connected_client.post(f"{F}/mf", json={"steps": 10})
    assert r.status_code == 502
    assert svc.relative_position == 0


async def test_move_does_not_re_enable_viewfinder_already_on(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    from backend.core.state import CameraState

    svc = install(app)
    await app.state.camera_service.transition(CameraState.LIVEVIEW)
    fake_camera._values["viewfinder"] = True
    before = fake_camera.calls.get("set_config", 0)
    await svc.move(5)
    assert fake_camera.calls["set_config"] - before == 1  # only manualfocusdrive
    fake_camera._values["viewfinder"] = False  # e.g. a capture switched it off
    await svc.move(5)
    assert fake_camera.viewfinder_on


async def test_stack_and_mf_refused_in_af_c_with_clear_error(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    del fake_camera._specs["liveviewaffocus"]  # body without the live view AF widget
    fake_camera._values["focusmode"] = "AF-C"
    r = await connected_client.post(f"{F}/stack", json=STACK)
    assert r.status_code == 409 and "AF-S" in r.json()["error"]["message"]
    r = await connected_client.post(f"{F}/mf", json={"steps": 3})
    assert r.status_code == 409
    assert (await connected_client.get("/api/v1/camera")).json()["leased_by"] is None


async def test_af_point_maps_normalized_to_full_sensor_pixels(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    assert (await c.post("/api/v1/liveview/start")).status_code < 300
    r = await c.post(f"{F}/point", json={"x": 0.5, "y": 0.5})
    assert r.status_code == 200 and r.json() == {"ok": True, "x": 2784, "y": 1856}
    assert fake_camera._values["changeafarea"] == "2784x1856"
    r = await c.post(f"{F}/point", json={"x": 1, "y": 1})
    assert r.json()["x"] == 5567 and r.json()["y"] == 3711


async def test_af_point_needs_liveview_and_valid_range(
    connected_client: httpx.AsyncClient,
) -> None:
    c = connected_client
    assert (await c.post(f"{F}/point", json={"x": 0.5, "y": 0.5})).status_code == 409
    assert (await c.post(f"{F}/point", json={"x": 1.5, "y": 0.5})).status_code == 422


async def test_af_point_unsupported_without_widget(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    await c.post("/api/v1/liveview/start")
    del fake_camera._specs["changeafarea"]
    r = await c.post(f"{F}/point", json={"x": 0.5, "y": 0.5})
    assert r.status_code == 501


async def test_full_size_not_cached_from_preview_fallback(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    await c.post("/api/v1/liveview/start")
    from backend.core.errors import CameraOperationFailed

    fake_camera.fail_next("get_config", 1, CameraOperationFailed())  # transient failure
    from backend.services import focus as focus_mod

    orig = dict(focus_mod._MODEL_SIZES)
    focus_mod._MODEL_SIZES.clear()
    try:
        first = await c.post(f"{F}/point", json={"x": 1, "y": 1})
        assert first.status_code == 200, first.text
        assert first.json()["x"] != 5567  # preview-sized fallback, not the sensor size
        second = await c.post(f"{F}/point", json={"x": 1, "y": 1})
        assert second.json()["x"] == 5567 and second.json()["y"] == 3711
    finally:
        focus_mod._MODEL_SIZES.update(orig)


SERVO, SINGLE = "Full-time-servo AF", "Single-servo AF"


async def test_mf_switches_servo_and_restores_when_idle(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["focusmode"] = "AF-C"  # irrelevant with liveviewaffocus
    fake_camera._values["liveviewaffocus"] = SERVO
    r = await connected_client.post(f"{F}/mf", json={"steps": 10})
    assert r.status_code == 200
    assert fake_camera._values["liveviewaffocus"] == SERVO


async def test_mf_in_user_liveview_restores_when_liveview_stops(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["liveviewaffocus"] = SERVO
    assert (await connected_client.post("/api/v1/liveview/start")).status_code < 300
    assert (await connected_client.post(f"{F}/mf", json={"steps": 10})).status_code == 200
    assert (await connected_client.post(f"{F}/mf", json={"steps": -10})).status_code == 200
    assert fake_camera._values["liveviewaffocus"] == SINGLE
    assert (await connected_client.post("/api/v1/liveview/stop")).status_code < 300
    for _ in range(100):
        if fake_camera._values["liveviewaffocus"] == SERVO:
            break
        await asyncio.sleep(0.02)
    assert fake_camera._values["liveviewaffocus"] == SERVO


async def test_mf_switch_failure_is_clear(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["liveviewaffocus"] = SERVO
    fake_camera._specs["liveviewaffocus"].readonly = True
    r = await connected_client.post(f"{F}/mf", json={"steps": 10})
    assert r.status_code == 409 and "Live View AF" in r.json()["error"]["message"]


async def test_stack_switches_servo_and_restores(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["liveviewaffocus"] = SERVO
    r = await connected_client.post(f"{F}/stack", json=STACK)
    assert r.status_code < 300
    job = await wait_job(connected_client, r.json()["id"])
    assert job["status"] == "completed"
    assert fake_camera._values["liveviewaffocus"] == SERVO


async def test_stack_restores_servo_on_failure(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["liveviewaffocus"] = SERVO
    real = fake_camera.set_config

    def boom(name: str, value: Any) -> None:
        if name == "manualfocusdrive" and fake_camera._values["liveviewaffocus"] == SINGLE:
            raise CameraOperationFailed("boom")
        real(name, value)

    fake_camera.set_config = boom  # type: ignore[method-assign]
    r = await connected_client.post(f"{F}/stack", json=STACK)
    job = await wait_job(connected_client, r.json()["id"])
    assert job["status"] == "failed"
    assert fake_camera._values["liveviewaffocus"] == SERVO


async def _mf_in_user_liveview(
    app: FastAPI, c: httpx.AsyncClient, fake: FakeCamera
) -> FocusService:
    svc = install(app)
    fake._values["liveviewaffocus"] = SERVO
    assert (await c.post("/api/v1/liveview/start")).status_code < 300
    assert (await c.post(f"{F}/mf", json={"steps": 10})).status_code == 200
    assert fake._values["liveviewaffocus"] == SINGLE and svc._lva_orig == SERVO
    return svc


async def _until(cond: Any) -> None:
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


async def test_restore_kept_while_leased_then_retried(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    cam = app.state.camera_service
    async with cam.lease("someone-else"):
        await cam.transition(CameraState.IDLE)
        await asyncio.sleep(0.5)
        assert svc._lva_orig == SERVO and fake_camera._values["liveviewaffocus"] == SINGLE
    await _until(lambda: fake_camera._values["liveviewaffocus"] == SERVO)
    assert svc._lva_orig is None


async def test_user_change_of_mode_is_not_overwritten(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    await app.state.camera_service.set_setting("liveviewaffocus", "Manual Focus (fixed)")
    await _until(lambda: svc._lva_orig is None)
    await app.state.camera_service.transition(CameraState.IDLE)
    await asyncio.sleep(0.2)
    assert fake_camera._values["liveviewaffocus"] == "Manual Focus (fixed)"


async def test_user_write_of_same_value_forgets_original(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    r = await connected_client.put("/api/v1/settings/liveviewaffocus", json={"value": SINGLE})
    assert r.status_code == 200
    assert svc._lva_orig is None
    await app.state.camera_service.transition(CameraState.IDLE)
    await asyncio.sleep(0.2)
    assert fake_camera._values["liveviewaffocus"] == SINGLE


async def test_app_writes_publish_setting_changed(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = install(app)
    fake_camera._values["liveviewaffocus"] = SERVO
    seen: list[Any] = []
    sub = app.state.camera_service.bus.subscribe()

    async def collect() -> None:
        async for ev in sub:
            if ev.type == EventType.SETTING_CHANGED and ev.data["name"] == "liveviewaffocus":
                seen.append(ev.data["value"])

    t = asyncio.create_task(collect())
    assert (await connected_client.post(f"{F}/mf", json={"steps": 10})).status_code == 200
    await _until(lambda: seen == [SINGLE, SERVO])
    assert svc._lva_orig is None
    t.cancel()


async def test_usb_loss_keeps_original_and_explicit_disconnect_drops_it(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    cam = app.state.camera_service
    cam._lost("usb")
    await asyncio.sleep(0.1)
    assert svc._lva_orig == SERVO
    await cam.connect()
    await _until(lambda: fake_camera._values["liveviewaffocus"] == SERVO)
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    await cam.disconnect()
    await _until(lambda: svc._lva_orig is None)


async def test_aclose_cancels_watcher(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    svc = await _mf_in_user_liveview(app, connected_client, fake_camera)
    watch = svc._lva_watch
    assert watch is not None and not watch.done()
    await svc.aclose()
    assert watch.done() and svc._lva_orig is None


async def test_cancelled_stack_keeps_partial_result(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    svc = install(app)
    gate = asyncio.Event()

    async def slow(_: float) -> None:
        gate.set()
        await asyncio.sleep(30)

    svc._sleep = slow
    jid = (await c.post(f"{F}/stack", json=STACK)).json()["id"]
    await gate.wait()
    assert (await c.delete(f"/api/v1/jobs/{jid}")).status_code == 200
    j = await wait_job(c, jid)
    assert j["status"] == "cancelled"
    assert j["result"]["file_count"] == 1 and j["result"]["folder"]
    assert j["result"]["returned_to_start"] is True and j["result"]["net_steps"] == 0


async def test_drive_past_end_of_travel_is_focus_limit(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera.focus_travel = 200
    r = await connected_client.post(f"{F}/mf", json={"steps": -50})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FOCUS_LIMIT"
    assert "closest" in r.json()["error"]["message"]
    r = await connected_client.post(f"{F}/mf", json={"steps": 300})
    assert r.status_code == 409 and "farthest" in r.json()["error"]["message"]


async def test_drive_switches_manual_focus_liveview_af_and_restores(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    manual = "Manual Focus (fixed)"
    fake_camera._values["liveviewaffocus"] = manual
    r = await connected_client.post(f"{F}/mf", json={"steps": 50})
    assert r.status_code == 200
    await _until(lambda: fake_camera._values["liveviewaffocus"] == manual)
