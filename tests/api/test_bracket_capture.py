"""POST /capture/bracket against the fake camera."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.api.v1.capture import build_capture_service
from backend.api.v1.settings import build_settings_service
from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed
from backend.core.state import CameraState
from backend.services.bracket_capture import BracketCaptureService

P = "/api/v1/capture/bracket"
TOUCHED = ("iso", "exposurecompensation", "shutterspeed", "f-number")


class Sleeper:
    def __init__(self) -> None:
        self.n = 0
        self.hook: Any = None

    async def sleep(self, s: float) -> None:
        self.n += 1
        if self.hook is not None:
            await self.hook(self.n)
        await asyncio.sleep(0)


def install(app: FastAPI, settle_s: float = 0.0) -> Sleeper:
    sl = Sleeper()
    st = app.state
    settings = st.services.get("settings", lambda: build_settings_service(st))
    capture = st.services.get("capture", lambda: build_capture_service(st))
    st.services.get(
        "bracket_capture",
        lambda: BracketCaptureService(
            st.camera_service,
            st.job_manager,
            st.event_bus,
            settings,
            capture,
            st.config_store,
            settle_s=settle_s,
            sleep=sl.sleep,
        ),
    )
    return sl


async def wait_job(c: httpx.AsyncClient, job_id: str, limit: float = 10) -> dict[str, Any]:
    deadline = time.monotonic() + limit
    while True:
        j = (await c.get(f"/api/v1/jobs/{job_id}")).json()
        if j["status"] in {"completed", "failed", "cancelled"}:
            return j
        assert time.monotonic() < deadline, j
        await asyncio.sleep(0.01)


def values(cam: FakeCamera) -> dict[str, Any]:
    return {k: cam._values[k] for k in TOUCHED}


async def run(c: httpx.AsyncClient, bracketing: dict[str, Any], **kw: Any) -> dict[str, Any]:
    r = await c.post(P, json={"bracketing": bracketing} | kw)
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "bracket"
    return await wait_job(c, r.json()["id"])


MODES: dict[str, tuple[dict[str, Any], int]] = {
    "steps": (
        {
            "mode": "steps",
            "steps": [
                {"settings": {"iso": "400"}, "label": "a"},
                {"settings": {"iso": "800", "shutterspeed": "1/500"}, "label": "b"},
            ],
        },
        2,
    ),
    "preset": ({"mode": "preset", "preset": "exposure_3"}, 3),
    "quick_sequence": ({"mode": "quick", "exposure": ["-1", "1"], "iso": ["400"]}, 3),
    "quick_paired": (
        {"mode": "quick", "exposure": ["-1", "1"], "iso": ["400", "800"], "combine_mode": "paired"},
        2,
    ),
}


@pytest.mark.parametrize("mode", list(MODES))
async def test_bracket_each_mode_restores_exactly(
    mode: str, app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    c = connected_client
    install(app)
    await app.state.camera_service.set_setting("iso", "320")
    await app.state.camera_service.set_setting("shutterspeed", "1/60")
    before = values(fake_camera)
    bracketing, n = MODES[mode]
    j = await run(c, bracketing, filename_prefix="hdr")
    assert j["status"] == "completed", j
    shots = j["result"]["shots"]
    assert [s["index"] for s in shots] == list(range(n))
    assert all(len(s["files"]) == 1 for s in shots)
    out = app.state.storage.root()
    assert all((out / f).is_file() for s in shots for f in s["files"])
    assert j["result"]["directory"].startswith("brackets/")
    assert all(f.startswith(j["result"]["directory"]) for s in shots for f in s["files"])
    assert all("/hdr_" in s["files"][0] for s in shots)
    assert values(fake_camera) == before
    cam = app.state.camera_service
    assert cam.state == CameraState.IDLE
    assert cam.status().leased_by is None


async def test_bracket_applies_each_step_value(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    seen: list[str] = []
    orig = fake_camera._do_capture

    def spy() -> Any:
        seen.append(str(fake_camera._values["iso"]))
        return orig()

    fake_camera._do_capture = spy  # type: ignore[method-assign]
    j = await run(
        connected_client,
        {
            "mode": "steps",
            "steps": [{"settings": {"iso": "400"}}, {"settings": {"iso": "800"}}],
        },
    )
    assert j["status"] == "completed"
    assert seen == ["400", "800"]


async def test_bracket_without_download_keeps_frames_on_camera(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    install(app)
    j = await run(connected_client, MODES["preset"][0], download=False)
    assert j["status"] == "completed"
    assert j["result"]["directory"] is None
    assert all(s["files"] == [] and len(s["camera_files"]) == 1 for s in j["result"]["shots"])


async def test_bracket_failure_mid_set_restores_and_releases(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    sl = install(app, settle_s=0.1)
    await app.state.camera_service.set_setting("iso", "320")
    before = values(fake_camera)

    async def hook(n: int) -> None:
        if n == 2:  # during step 2's settle: its capture fails
            fake_camera.fail_next("capture", 1, CameraOperationFailed("boom"))

    sl.hook = hook
    j = await run(connected_client, MODES["preset"][0])
    assert j["status"] == "failed"
    assert j["error_code"] == "CAMERA_OPERATION_FAILED"
    assert values(fake_camera) == before
    cam = app.state.camera_service
    assert cam.state == CameraState.IDLE
    assert cam.status().leased_by is None


async def test_bracket_invalid_values_rejected_before_any_shot(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    install(app)
    r = await connected_client.post(
        P,
        json={
            "bracketing": {
                "mode": "steps",
                "steps": [{"settings": {"iso": "400"}}, {"settings": {"iso": "999999"}}],
            }
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SETTING_INVALID"
    assert fake_camera.calls.get("capture", 0) == 0


async def test_bracket_needs_two_steps(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    install(app)
    r = await connected_client.post(P, json={"bracketing": {"mode": "none"}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONFIG_INVALID"


async def test_bracket_refused_under_other_lease(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    install(app)
    async with app.state.camera_service.lease("someone"):
        r = await connected_client.post(P, json={"bracketing": MODES["preset"][0]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CAMERA_BUSY"


async def test_bracket_disconnected_is_503(app: FastAPI, client: httpx.AsyncClient) -> None:
    install(app)
    r = await client.post(P, json={"bracketing": MODES["preset"][0]})
    assert r.status_code == 503


async def test_bracket_exclusive_second_job_conflicts(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    sl = install(app, settle_s=0.1)
    gate, reached = asyncio.Event(), asyncio.Event()

    async def hook(n: int) -> None:
        if n == 1:
            reached.set()
            await gate.wait()

    sl.hook = hook
    r = await c.post(P, json={"bracketing": MODES["preset"][0]})
    assert r.status_code == 202
    await asyncio.wait_for(reached.wait(), 5)
    r2 = await c.post(P, json={"bracketing": MODES["preset"][0]})
    assert r2.status_code == 409  # lease held by the running bracket job
    gate.set()
    assert (await wait_job(c, r.json()["id"]))["status"] == "completed"


async def test_bracket_holds_lease_from_request_so_concurrent_job_gets_409(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    c = connected_client
    sl = install(app, settle_s=0.01)
    gate, reached = asyncio.Event(), asyncio.Event()

    async def hook(n: int) -> None:
        reached.set()
        await gate.wait()

    sl.hook = hook
    r = await c.post(P, json={"bracketing": MODES["preset"][0]})
    assert r.status_code == 202
    assert app.state.camera_service.status().leased_by == "bracket"
    r2 = await c.post("/api/v1/capture/bulb", json={"seconds": 2})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "CAMERA_BUSY"
    await asyncio.wait_for(reached.wait(), 5)
    gate.set()
    assert (await wait_job(c, r.json()["id"]))["status"] == "completed"
    assert app.state.camera_service.status().leased_by is None
