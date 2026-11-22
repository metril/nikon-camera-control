"""BulbService: status maths and preflight."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from backend.api.schemas.exposure import BulbRequest
from backend.core.errors import CameraNotConnected, InvalidState
from backend.core.state import CameraState
from backend.services.bulb import BulbService, _Run


def make(app: FastAPI, t: list[float]) -> BulbService:
    st = app.state
    return BulbService(
        st.camera_service, st.job_manager, st.event_bus, st.output_dir, lambda: None,
        clock=lambda: t[0],
    )  # fmt: skip


async def test_status_idle_and_running(app: FastAPI, client: object) -> None:
    t = [100.0]
    svc = make(app, t)
    assert svc.status().active is False
    svc._run = _Run("j1", 10.0)
    s = svc.status()
    assert s.active and s.elapsed_s == 0 and s.remaining_s == 10  # not opened yet
    svc._run.started = 100.0
    t[0] = 104.0
    s = svc.status()
    assert (s.elapsed_s, s.remaining_s, s.job_id) == (4.0, 6.0, "j1")
    t[0] = 500.0
    assert svc.status().remaining_s == 0.0
    svc._run.ended = 107.0
    assert svc.status().elapsed_s == 7.0


async def test_start_requires_connection(app: FastAPI, client: object) -> None:
    with pytest.raises(CameraNotConnected):
        await make(app, [0.0]).start(BulbRequest(seconds=2))


async def test_start_requires_idle_state(app: FastAPI, connected_client: object) -> None:
    await app.state.camera_service.transition(CameraState.LIVEVIEW)
    with pytest.raises(InvalidState):
        await make(app, [0.0]).start(BulbRequest(seconds=2))
