"""BulbService: status maths and preflight."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from backend.api.schemas.exposure import BulbRequest
from backend.core.errors import CameraNotConnected, CameraOperationFailed, InvalidState
from backend.core.state import CameraState
from backend.services.bulb import BulbService, _Run


def make(app: FastAPI, t: list[float]) -> BulbService:
    st = app.state
    return BulbService(
        st.camera_service, st.job_manager, st.event_bus, st.storage, lambda: None,
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


async def test_cancel_during_open_waits_for_in_flight_open_and_reports_it(
    app: FastAPI, client: object
) -> None:
    svc = make(app, [0.0])
    gate, calls = asyncio.Event(), []

    async def slow_set_bulb(v: int) -> None:
        await gate.wait()
        calls.append(v)

    svc._set_bulb = slow_set_bulb  # type: ignore[method-assign,assignment]
    t = asyncio.create_task(svc._open(_Run("j", 5.0)))
    await asyncio.sleep(0.01)
    t.cancel()
    await asyncio.sleep(0.01)
    assert not t.done()  # still waiting for the open that cannot be withdrawn
    gate.set()
    cancel = await t
    assert calls == [1] and isinstance(cancel, asyncio.CancelledError)


async def test_second_cancel_during_close_retry_does_not_skip_close(
    app: FastAPI, client: object
) -> None:
    svc = make(app, [0.0])
    gate, reached, calls = asyncio.Event(), asyncio.Event(), []

    async def set_bulb(v: int) -> None:
        calls.append(v)
        if len(calls) == 1:
            raise CameraOperationFailed("flaky")

    async def sleep(_: float) -> None:
        reached.set()
        await gate.wait()

    svc._set_bulb = set_bulb  # type: ignore[method-assign,assignment]
    svc._sleep = sleep
    run = _Run("j", 5.0)
    t = asyncio.create_task(svc._close_shielded(run))
    await reached.wait()
    t.cancel()  # cancel lands in the retry sleep
    await asyncio.sleep(0.01)
    gate.set()
    cancel = await t
    assert calls == [0, 0] and run.ended is not None
    assert isinstance(cancel, asyncio.CancelledError)
