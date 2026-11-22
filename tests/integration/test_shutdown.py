"""App shutdown must run job cleanup while the camera is still there."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from backend.api.schemas.exposure import BracketRequest, BulbRequest
from backend.api.v1.capture import build_capture_service
from backend.api.v1.exposure import build_bulb_service
from backend.api.v1.focus import build_focus_service
from backend.api.v1.settings import build_settings_service
from backend.camera.fake import FakeCamera
from backend.services.bracket_capture import BracketCaptureService

BOUND_S = 10.0


async def until(pred: Callable[[], bool], limit: float = 5.0) -> None:
    deadline = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


async def shutdown(app: FastAPI, cm: Any) -> float:
    t0 = time.monotonic()
    await cm.__aexit__(None, None, None)
    return time.monotonic() - t0


async def test_shutdown_during_bulb_closes_shutter_and_restores_speed(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    cm = app.router.lifespan_context(app)
    await cm.__aenter__()
    await app.state.camera_service.connect()
    before = fake_camera._values["shutterspeed"]
    svc = app.state.services.get("bulb", lambda: build_bulb_service(app.state))
    await svc.start(BulbRequest(seconds=600))
    await until(lambda: fake_camera._values["bulb"] is True)
    assert await shutdown(app, cm) < BOUND_S
    assert fake_camera._values["bulb"] is False
    assert fake_camera._values["shutterspeed"] == before
    assert app.state.job_manager.list(status=None)[0].status == "cancelled"


async def test_shutdown_during_focus_stack_returns_focus_and_viewfinder_off(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    cm = app.router.lifespan_context(app)
    await cm.__aenter__()
    await app.state.camera_service.connect()
    svc = app.state.services.get("focus", lambda: build_focus_service(app.state))
    await svc.start_stack(
        steps_per_shot=10,
        shots=3,
        direction="near_to_far",
        settle_ms=60_000,
        return_to_start=True,
        name=None,
    )
    await until(lambda: svc.relative_position == 10)
    assert await shutdown(app, cm) < BOUND_S
    assert svc.relative_position == 0
    assert not fake_camera.viewfinder_on


async def test_shutdown_during_bracket_restores_settings(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    cm = app.router.lifespan_context(app)
    await cm.__aenter__()
    await app.state.camera_service.connect()
    st = app.state
    svc = BracketCaptureService(
        st.camera_service,
        st.job_manager,
        st.event_bus,
        st.services.get("settings", lambda: build_settings_service(st)),
        st.services.get("capture", lambda: build_capture_service(st)),
        st.config_store,
        settle_s=60.0,
    )
    before = fake_camera._values["iso"]
    req = BracketRequest.model_validate(
        {
            "bracketing": {
                "mode": "steps",
                "steps": [{"settings": {"iso": "800"}}, {"settings": {"iso": "1600"}}],
            }
        }
    )
    await svc.start(req)
    await until(lambda: fake_camera._values["iso"] == "800")
    assert await shutdown(app, cm) < BOUND_S
    assert fake_camera._values["iso"] == before
