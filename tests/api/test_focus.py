import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed
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
            st.output_dir,
            sleep=sleep,
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
