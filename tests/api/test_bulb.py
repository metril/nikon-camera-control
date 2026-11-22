"""POST/GET /capture/bulb against the fake camera (injected clock and sleep)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.api.schemas.common import EventType
from backend.camera.fake import CARD_FOLDER, FakeCamera
from backend.core.errors import CameraOperationFailed
from backend.core.state import CameraState
from backend.services import bulb as bulb_mod
from backend.services.bulb import BulbService

B = "/api/v1/capture/bulb"


class FakeTime:
    """Virtual clock; ``sleep`` advances it. ``hook(n)`` runs before the n-th sleep and may
    block (cancel tests) or inject faults."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []
        self.hook: Any = None

    def clock(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        if self.hook is not None:
            await self.hook(len(self.sleeps))
        self.t += s
        await asyncio.sleep(0)


def install(app: FastAPI) -> FakeTime:
    ft = FakeTime()
    st = app.state
    from backend.api.v1.files import build_file_service

    files = st.services.get("files", lambda: build_file_service(st))
    st.services.get(
        "bulb",
        lambda: BulbService(
            st.camera_service,
            st.job_manager,
            st.event_bus,
            st.output_dir,
            files.index.invalidate,
            quiet_window_s=0.02,
            sleep=ft.sleep,
            clock=ft.clock,
        ),
    )
    return ft


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bulb_mod, "CLOSE_RETRY_DELAY_S", 0.0)


async def wait_job(c: httpx.AsyncClient, job_id: str, limit: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + limit
    while True:
        j = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        if j["status"] in {"completed", "failed", "cancelled"}:
            return j
        assert time.monotonic() < deadline, j
        await asyncio.sleep(0.01)


def card_files(cam: FakeCamera) -> list[str]:
    return sorted(cam._files[CARD_FOLDER])


async def test_bulb_happy_path(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    ft = install(app)
    await app.state.camera_service.set_setting("shutterspeed", "1/60")
    r = await c.post(B, json={"seconds": 5, "filename_prefix": "star"})
    assert r.status_code == 202
    job = r.json()
    assert job["kind"] == "bulb"
    j = await wait_job(c, job["id"])
    assert j["status"] == "completed", j
    assert ft.sleeps[:5] == [1.0] * 5
    assert j["result"]["seconds"] == 5
    (name,) = j["result"]["files"]
    assert (app.state.output_dir / name).is_file()
    assert "star_" in name
    assert fake_camera._values["shutterspeed"] == "1/60"  # real prior value restored
    assert fake_camera._values["bulb"] is False
    assert len(card_files(fake_camera)) == 1
    cam = app.state.camera_service
    assert cam.state == CameraState.IDLE
    assert cam.status().leased_by is None
    assert (await c.get(B)).json()["active"] is False


async def test_bulb_reports_progress_and_status(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    ft = install(app)
    seen: list[dict[str, Any]] = []

    async def hook(n: int) -> None:
        if n == 3:
            seen.append((await c.get(B)).json())

    ft.hook = hook
    job = (await c.post(B, json={"seconds": 4, "download": False})).json()
    j = await wait_job(c, job["id"])
    assert j["status"] == "completed"
    assert j["result"]["files"] == []
    st = seen[0]
    assert st["active"] is True and st["job_id"] == job["id"]
    assert st["elapsed_s"] == 2.0 and st["remaining_s"] == 2.0


async def test_bulb_outside_manual_mode_only_warns(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    fake_camera._values["expprogram"] = "A"
    r = await connected_client.post(B, json={"seconds": 2})
    assert r.status_code == 202
    j = await wait_job(connected_client, r.json()["id"])
    assert j["status"] == "completed", j
    assert any("not M" in w for w in j["result"]["warnings"])
    assert fake_camera._values["bulb"] is False


async def test_bulb_open_failure_names_camera_error_and_mode_hint(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    ft = install(app)
    fake_camera._values["expprogram"] = "A"
    fake_camera.fail_next("set_config", 3, CameraOperationFailed("Bulb not available"))
    ft.hook = None
    j = await wait_job(
        connected_client, (await connected_client.post(B, json={"seconds": 2})).json()["id"]
    )
    assert j["status"] == "failed"
    assert "Bulb not available" in j["error"] and "M" in j["error"]
    assert fake_camera._values["bulb"] is False


async def test_bulb_without_bulb_choice_still_runs(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    import dataclasses

    spec = fake_camera._specs["shutterspeed"]
    fake_camera._specs["shutterspeed"] = dataclasses.replace(
        spec, choices=tuple(c for c in spec.choices if c != "Bulb")
    )
    j = await wait_job(
        connected_client, (await connected_client.post(B, json={"seconds": 2})).json()["id"]
    )
    assert j["status"] == "completed", j
    assert fake_camera._values["shutterspeed"] == "1/250"


async def test_cancel_while_open_in_flight_still_closes_shutter(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    install(app)
    svc = app.state.services.get("bulb", lambda: None)
    real = svc._set_bulb
    gate, reached = asyncio.Event(), asyncio.Event()

    async def slow(v: int) -> None:
        if v == 1:
            reached.set()
            await gate.wait()
        await real(v)

    svc._set_bulb = slow
    job = (await c.post(B, json={"seconds": 600})).json()
    await asyncio.wait_for(reached.wait(), 5)
    d = asyncio.create_task(c.delete(f"/api/v1/jobs/{job['id']}"))
    await asyncio.sleep(0.05)
    gate.set()  # the open lands after the cancel
    r = await d
    assert r.json()["status"] == "cancelled", r.text
    assert fake_camera._values["bulb"] is False
    assert app.state.camera_service.status().leased_by is None


async def test_cancel_while_waiting_for_missing_file_returns_promptly(
    app: FastAPI,
    connected_client: httpx.AsyncClient,
    fake_camera: FakeCamera,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = connected_client
    install(app)
    monkeypatch.setattr(bulb_mod, "CANCEL_COLLECT_GRACE_S", 0.1)
    monkeypatch.setattr(
        BulbService, "_poll", staticmethod(lambda b: None)
    )  # FILE_ADDED never comes
    job = (await c.post(B, json={"seconds": 2})).json()
    deadline = time.monotonic() + 5
    while not (  # shutter closed, now stuck collecting
        fake_camera._values["bulb"] is False and fake_camera.calls.get("set_config", 0) >= 3
    ):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    t0 = time.monotonic()
    r = await c.delete(f"/api/v1/jobs/{job['id']}")
    assert time.monotonic() - t0 < 3
    assert r.json()["status"] == "cancelled"
    assert app.state.camera_service.status().leased_by is None


async def test_second_exposure_job_gets_409_at_request_time_when_lease_taken(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    ft = install(app)
    gate, reached = asyncio.Event(), asyncio.Event()

    async def hook(n: int) -> None:
        if n == 2:
            reached.set()
            await gate.wait()

    ft.hook = hook
    job = (await c.post(B, json={"seconds": 5})).json()
    await asyncio.wait_for(reached.wait(), 5)
    br = {"bracketing": {"mode": "preset", "preset": "exposure_3"}}
    r = await c.post("/api/v1/capture/bracket", json=br)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
    gate.set()
    await wait_job(c, job["id"])


async def test_bulb_refused_under_other_lease(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    install(app)
    async with app.state.camera_service.lease("someone"):
        r = await connected_client.post(B, json={"seconds": 2})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CAMERA_BUSY"


async def test_bulb_disconnected_is_503(app: FastAPI, client: httpx.AsyncClient) -> None:
    install(app)
    r = await client.post(B, json={"seconds": 2})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "CAMERA_NOT_CONNECTED"


async def test_bulb_validates_seconds(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    for s in (0, 0.5, 3601):
        r = await connected_client.post(B, json={"seconds": s})
        assert r.status_code == 422


async def test_bulb_second_job_conflicts(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    c = connected_client
    ft = install(app)
    gate = asyncio.Event()
    reached = asyncio.Event()

    async def hook(n: int) -> None:
        if n == 2:
            reached.set()
            await gate.wait()

    ft.hook = hook
    job = (await c.post(B, json={"seconds": 5})).json()
    await asyncio.wait_for(reached.wait(), 5)
    r = await c.post(B, json={"seconds": 5})
    assert r.status_code == 409
    gate.set()
    assert (await wait_job(c, job["id"]))["status"] == "completed"


async def test_cancel_mid_exposure_closes_shutter_and_keeps_frame(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    ft = install(app)
    reached = asyncio.Event()

    async def hook(n: int) -> None:
        if n == 3:
            reached.set()
            await asyncio.Event().wait()  # park until cancelled

    ft.hook = hook
    job = (await c.post(B, json={"seconds": 600})).json()
    await asyncio.wait_for(reached.wait(), 5)
    assert fake_camera._values["bulb"] is True
    r = await c.delete(f"/api/v1/jobs/{job['id']}")
    assert r.status_code == 200 and r.json()["status"] == "cancelled", r.text
    assert fake_camera._values["bulb"] is False
    assert len(card_files(fake_camera)) == 1
    assert len(list(app.state.output_dir.glob("*.JPG"))) == 1  # frame still downloaded
    cam = app.state.camera_service
    assert cam.state == CameraState.IDLE
    assert cam.status().leased_by is None
    assert fake_camera._values["shutterspeed"] == "1/250"


async def test_close_failure_is_retried(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    ft = install(app)

    async def hook(n: int) -> None:
        if n == 1:
            fake_camera.fail_next("set_config", 2, CameraOperationFailed("nope"))

    ft.hook = hook
    job = (await c.post(B, json={"seconds": 2})).json()
    j = await wait_job(c, job["id"])
    assert j["status"] == "completed", j
    assert fake_camera._values["bulb"] is False
    assert len(card_files(fake_camera)) == 1


async def test_close_failure_reported_loudly(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    ft = install(app)

    async def hook(n: int) -> None:
        if n == 1:
            fake_camera.fail_next("set_config", bulb_mod.CLOSE_ATTEMPTS, CameraOperationFailed("x"))

    ft.hook = hook
    async with app.state.event_bus.subscribe() as sub:
        job = (await c.post(B, json={"seconds": 2})).json()
        j = await wait_job(c, job["id"])
        assert j["status"] == "failed"
        assert "SHUTTER" in j["error"] and j["error_code"] == "BULB_SHUTTER_OPEN"
        codes = []
        while True:
            try:
                ev = await asyncio.wait_for(sub.__anext__(), 0.2)
            except TimeoutError:
                break
            if ev.type == EventType.ERROR:
                codes.append(ev.data["code"])
    assert "BULB_SHUTTER_OPEN" in codes
    assert app.state.camera_service.state == CameraState.ERROR
    assert app.state.camera_service.status().leased_by is None
    assert (await c.get(B)).json()["active"] is False


async def test_routes_do_not_clash_with_capture(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    assert {"/api/v1/capture", "/api/v1/capture/trigger"} <= set(paths)
    assert paths["/api/v1/capture/bulb"]["post"]["operationId"] == "start_bulb_capture"
    assert paths["/api/v1/capture/bulb"]["get"]["operationId"] == "get_bulb_status"
    assert paths["/api/v1/capture/bracket"]["post"]["operationId"] == "start_bracket_capture"
