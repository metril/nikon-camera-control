"""CameraService regression tests against a local StubBackend and RecordingBus."""

from __future__ import annotations

import asyncio
import collections
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

import pytest

from backend.api.schemas.common import EventType
from backend.camera.backend import (
    CameraBackend,
    CameraEvent,
    CameraFilePath,
    ConfigType,
    ConfigWidget,
    StorageInfo,
)
from backend.camera.backend import EventType as CamEvent
from backend.core.camera_service import CameraService, Priority
from backend.core.config_store import AppConfig, CameraConfig, ConfigStore
from backend.core.errors import (
    CameraBusy,
    CameraIOError,
    CameraNotConnected,
    CameraNotFound,
    CameraOperationFailed,
    CameraTimeout,
    InvalidState,
)
from backend.core.events import EventBus
from backend.core.state import CameraState as S

A_NEF = CameraFilePath("/store/DCIM", "DSC_1.NEF")
A_JPG = CameraFilePath("/store/DCIM", "DSC_1.JPG")


class RecordingBus:
    """EventBus test double: records every publish (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def publish(self, type: EventType, data: dict[str, Any] | None = None) -> None:
        with self._lock:
            self.events.append((str(type.value), dict(data or {})))

    def of(self, type_: EventType) -> list[dict[str, Any]]:
        with self._lock:
            return [d for t, d in self.events if t == type_.value]

    def states(self) -> list[str]:
        return [d["state"] for d in self.of(EventType.CAMERA_STATE)]


class StubBackend:
    """Minimal CameraBackend with hang/failure hooks."""

    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0
        self.storage = [StorageInfo("SD", "/store", 100, 50, 10, "rw")]
        self._open = False
        self.fail_open: Exception | None = None
        self.fail_battery: Exception | None = None
        self.battery: str = "90%"
        self.battery_reads = 0
        self.list_calls = 0
        self.get_calls = 0
        self.preview_calls = 0
        self.end_previews = 0
        self.invalidations = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.events: collections.deque[CameraEvent] = collections.deque()
        self.on_capture: list[CameraEvent] = []  # events the capture itself produces
        self.values = {"iso": "100", "aperture": "5.6"}
        self.fail_events: Exception | None = None

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self.fail_open is not None:
            raise self.fail_open
        self.opens += 1
        self._open = True

    def close(self) -> None:
        self.closes += 1
        self._open = False

    def model(self) -> str:
        return "Stub D500"

    def _leaf(self, name: str, value: Any) -> ConfigWidget:
        return ConfigWidget(
            name=name, label=name, path=f"/main/{name}", type=ConfigType.TEXT, value=value
        )

    def list_config(self) -> list[ConfigWidget]:
        self.list_calls += 1
        leaves = tuple(self._leaf(k, v) for k, v in self.values.items())
        sec = ConfigWidget("main", "Main", "/main", ConfigType.SECTION, children=leaves)
        return [sec]

    def storage_info(self) -> list[StorageInfo]:
        return self.storage

    def get_config(self, name: str) -> ConfigWidget:
        if name == "hang":
            self.entered.set()
            self.release.wait(5)
            return self._leaf(name, None)
        if name == "batterylevel":
            self.battery_reads += 1
            if self.fail_battery is not None:
                raise self.fail_battery
            return self._leaf(name, self.battery)
        self.get_calls += 1
        return self._leaf(name, self.values.get(name, "?"))

    def set_config(self, name: str, value: str | int | float | bool) -> None:
        self.values[name] = str(value)

    def capture(self) -> CameraFilePath:
        self.events.extend(self.on_capture)
        self.on_capture.clear()
        return A_NEF

    def wait_for_event(self, timeout_s: float) -> CameraEvent:
        if self.fail_events is not None:
            raise self.fail_events
        if self.events:
            return self.events.popleft()
        time.sleep(min(timeout_s, 0.005))
        return CameraEvent(CamEvent.TIMEOUT)

    def capture_preview(self) -> bytes:
        self.preview_calls += 1
        return b"jpeg"

    def end_preview(self) -> None:
        self.end_previews += 1

    def invalidate_preview(self) -> None:
        self.invalidations += 1

    def summary(self) -> str:
        return "stub"


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.backend = StubBackend()
        self.bus = RecordingBus()
        self.factory_calls = 0
        self.services: list[CameraService] = []

    def _factory(self) -> CameraBackend:
        self.factory_calls += 1
        return cast(CameraBackend, self.backend)

    def set_cfg(self, svc: CameraService, **cam: Any) -> None:
        cam.setdefault("keepalive_enabled", False)
        cfg = AppConfig.model_construct(camera=CameraConfig.model_construct(**cam))
        svc._config._config = cfg  # noqa: SLF001 - live config swap, as the UI would do

    async def make(
        self,
        *,
        connect: bool = True,
        quiet: float = 0.02,
        disconnect_wait: float = 0.1,
        **cam: Any,
    ) -> CameraService:
        cam.setdefault("keepalive_enabled", False)
        cam.setdefault("connect_retries", 0)
        cfg = AppConfig.model_construct(camera=CameraConfig.model_construct(**cam))
        store = ConfigStore(self.tmp / "config.json", initial=cfg)
        svc = CameraService(
            self._factory,
            store,
            cast(EventBus, self.bus),
            event_quiet_window_s=quiet,
            disconnect_wait_s=disconnect_wait,
        )
        svc._close_wait_s = 0.1  # noqa: SLF001
        svc._stop_wait_s = 0.1  # noqa: SLF001
        self.services.append(svc)
        await svc.start()
        if connect:
            await svc.connect()
        return svc


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    e = Env(tmp_path)
    yield e
    e.backend.release.set()
    for svc in e.services:
        await svc.stop()


async def wait_until(pred: Callable[[], bool], timeout: float = 10.0) -> None:  # noqa: ASYNC109
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


def hang(b: CameraBackend) -> Any:
    return b.get_config("hang")


def worker_threads(svc: CameraService) -> int:
    """Live worker threads started by this service only (other tests' threads ignored)."""
    prefix = svc._thread_prefix  # noqa: SLF001
    return sum(1 for t in threading.enumerate() if t.name.startswith(prefix) and t.is_alive())


# 1. priority queue ---------------------------------------------------------------------
async def test_priority_order_and_fifo(env: Env) -> None:
    svc = await env.make()
    order: list[str] = []

    def rec(tag: str) -> Callable[[CameraBackend], str]:
        def _f(_b: CameraBackend) -> str:
            order.append(tag)
            return tag

        return _f

    blocker = asyncio.create_task(svc.call(hang, timeout=5))
    await wait_until(env.backend.entered.is_set)
    tasks = []
    for tag, pr in [
        ("preview", Priority.PREVIEW),
        ("keepalive", Priority.KEEPALIVE),
        ("capture", Priority.CAPTURE),
        ("control1", Priority.CONTROL),
        ("control2", Priority.CONTROL),
    ]:
        tasks.append(asyncio.create_task(svc.call(rec(tag), priority=pr)))
        await asyncio.sleep(0)
    env.backend.release.set()
    await blocker
    assert await asyncio.gather(*tasks) == [
        "preview",
        "keepalive",
        "capture",
        "control1",
        "control2",
    ]
    assert order == ["control1", "control2", "capture", "keepalive", "preview"]


async def test_background_runs_after_live_view_frames(env: Env) -> None:
    svc = await env.make()
    order: list[str] = []

    def rec(tag: str) -> Callable[[CameraBackend], str]:
        def _f(_b: CameraBackend) -> str:
            order.append(tag)
            return tag

        return _f

    blocker = asyncio.create_task(svc.call(hang, timeout=5))
    await wait_until(env.backend.entered.is_set)
    bg = asyncio.create_task(svc.call(rec("bg"), priority=Priority.BACKGROUND))
    await asyncio.sleep(0)
    frame = asyncio.create_task(svc.call(rec("frame"), priority=Priority.PREVIEW))
    await asyncio.sleep(0)
    env.backend.release.set()
    await blocker
    await asyncio.gather(bg, frame)
    assert order == ["frame", "bg"]


async def test_cancelled_queued_call_never_executes(env: Env) -> None:
    svc = await env.make()
    ran: list[str] = []
    blocker = asyncio.create_task(svc.call(hang, timeout=5))
    await wait_until(env.backend.entered.is_set)
    queued = asyncio.create_task(svc.call(lambda _b: ran.append("x"), priority=Priority.BACKGROUND))
    await asyncio.sleep(0.05)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    env.backend.release.set()
    await blocker
    assert await svc.call(lambda _b: ran.append("after")) is None
    assert ran == ["after"]
    assert svc.state != S.ERROR


async def test_exception_propagates(env: Env) -> None:
    svc = await env.make()

    def boom(_b: CameraBackend) -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await svc.call(boom)
    assert svc.state == S.IDLE


# 2. timeout ----------------------------------------------------------------------------
async def test_timeout_abandons_resets_without_thread_pileup(env: Env) -> None:
    svc = await env.make()
    stuck = asyncio.create_task(svc.call(hang, timeout=0.05))
    await wait_until(env.backend.entered.is_set)
    queued = asyncio.create_task(svc.call(lambda b: "late", timeout=5))
    await asyncio.sleep(0)
    with pytest.raises(CameraTimeout):
        await stuck
    with pytest.raises(CameraTimeout):
        await queued
    assert svc.state == S.ERROR
    assert worker_threads(svc) == 1
    assert env.backend.closes == 0  # reset only after the stuck call returns
    env.backend.release.set()
    await wait_until(lambda: svc.state == S.IDLE)
    assert (env.backend.opens, env.backend.closes) == (2, 1)
    assert worker_threads(svc) == 1
    assert await svc.call(lambda b: "ok") == "ok"


async def test_queued_call_timeout_does_not_escalate_to_error(env: Env) -> None:
    svc = await env.make()
    ran: list[int] = []
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    with pytest.raises(CameraTimeout):
        await svc.call(lambda b: ran.append(1), timeout=0.05)  # still queued behind blocker
    assert svc.state == S.IDLE
    env.backend.release.set()
    await blocker
    assert await svc.call(lambda b: "ok") == "ok"
    assert ran == [] and svc.state == S.IDLE  # abandoned item was skipped, no reset happened
    assert (env.backend.opens, env.backend.closes) == (1, 0)


# 3. preview coalescing ----------------------------------------------------------------
async def test_preview_coalesced(env: Env) -> None:
    svc = await env.make()
    with pytest.raises(InvalidState):
        await svc.preview_frame()
    await svc.transition(S.LIVEVIEW)
    blocker = asyncio.create_task(svc.call(hang, timeout=5))
    await wait_until(env.backend.entered.is_set)
    frames = [asyncio.create_task(svc.preview_frame()) for _ in range(4)]
    await asyncio.sleep(0)
    env.backend.release.set()
    await blocker
    assert await asyncio.gather(*frames) == [b"jpeg"] * 4
    assert env.backend.preview_calls == 1
    assert await svc.preview_frame() == b"jpeg"
    assert env.backend.preview_calls == 2


async def test_coalesced_preview_timeout_wakes_all_waiters(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.core.camera_service._PREVIEW_TIMEOUT_S", 0.1)
    svc = await env.make()
    await svc.transition(S.LIVEVIEW)
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    frames = [asyncio.create_task(svc.preview_frame()) for _ in range(3)]
    results = await asyncio.wait_for(asyncio.gather(*frames, return_exceptions=True), 30)
    assert all(isinstance(r, CameraTimeout) for r in results)
    assert svc.state == S.LIVEVIEW
    env.backend.release.set()
    await blocker


async def test_disconnect_fails_shared_preview_waiters(env: Env) -> None:
    svc = await env.make()
    await svc.transition(S.LIVEVIEW)
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    frames = [asyncio.create_task(svc.preview_frame()) for _ in range(3)]
    await asyncio.sleep(0)
    await svc.disconnect()
    results = await asyncio.wait_for(asyncio.gather(*frames, return_exceptions=True), 30)
    assert all(isinstance(r, CameraNotConnected) for r in results)
    assert isinstance(
        (await asyncio.gather(blocker, return_exceptions=True))[0], CameraNotConnected
    )


# 4. state machine ---------------------------------------------------------------------
async def test_invalid_transition_and_events(env: Env) -> None:
    svc = await env.make()
    assert env.bus.states() == ["connecting", "idle"]
    with pytest.raises(InvalidState):
        await svc.transition(S.IDLE)  # same state
    with pytest.raises(InvalidState):
        await svc.transition(S.CONNECTING)
    assert await svc.transition(S.LIVEVIEW) == S.IDLE
    assert env.bus.of(EventType.CAMERA_STATE)[-1] == {"state": "liveview", "previous": "idle"}
    assert svc.state == S.LIVEVIEW


async def test_capture_restores_prior_state(env: Env) -> None:
    svc = await env.make()
    await svc.capture(timeout=0.02)
    assert svc.state == S.IDLE
    await svc.transition(S.LIVEVIEW)
    await svc.capture(timeout=0.02)
    assert svc.state == S.LIVEVIEW
    assert env.bus.states()[-2:] == ["capturing", "liveview"]


# 5. connect / disconnect / stop ---------------------------------------------------------
async def test_connect_idempotent_and_events(env: Env) -> None:
    svc = await env.make(connect=False)
    st = await svc.connect()
    st2 = await svc.connect()
    assert st.connected and st2.connected and st.model == "Stub D500"
    assert env.factory_calls == 1 and env.backend.opens == 1
    assert env.bus.of(EventType.CAMERA_CONNECTED) == [{"model": "Stub D500", "serial": "?"}]
    assert st.connected_at is not None


async def test_connect_failure_returns_to_disconnected(env: Env) -> None:
    env.backend.fail_open = CameraNotFound()
    svc = await env.make(connect=False)
    with pytest.raises(CameraNotFound):
        await svc.connect()
    assert svc.state == S.DISCONNECTED
    env.backend.fail_open = None
    assert (await svc.connect()).state == S.IDLE


async def test_disconnect_fast_and_idempotent(env: Env) -> None:
    svc = await env.make()
    t0 = time.monotonic()
    st = await svc.disconnect()
    await svc.disconnect()
    assert time.monotonic() - t0 < 0.5
    assert st.state == S.DISCONNECTED and env.backend.closes == 1
    assert len(env.bus.of(EventType.CAMERA_DISCONNECTED)) == 1
    with pytest.raises(CameraNotConnected):
        await svc.call(lambda b: 1)


async def test_disconnect_waits_for_inflight_call_then_closes(env: Env) -> None:
    svc = await env.make(disconnect_wait=30.0)
    thread = svc._worker.thread  # type: ignore[union-attr]  # noqa: SLF001
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    loop = asyncio.get_running_loop()
    loop.call_later(0.1, env.backend.release.set)
    await svc.disconnect()
    assert (await blocker).value is None  # the in-flight call finished normally
    assert env.backend.closes == 1 and not env.backend.is_open
    assert svc._worker is not None  # noqa: SLF001 - worker kept, not abandoned
    assert thread.is_alive()


async def test_abandoned_worker_never_closes_backend_of_newer_worker(env: Env) -> None:
    svc = await env.make()
    old = svc._worker.thread  # type: ignore[union-attr]  # noqa: SLF001
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    await svc.disconnect()  # bounded wait elapses -> worker abandoned
    with pytest.raises(CameraNotConnected):
        await blocker
    svc._zombie_wait_s = 0.05  # noqa: SLF001
    with pytest.raises(CameraTimeout):  # never open while the abandoned call is still hung
        await svc.connect()
    env.backend.release.set()
    await wait_until(lambda: not old.is_alive())
    await svc.connect()  # new worker, same backend object from the factory
    assert env.backend.is_open  # the old worker closed its own backend before the new open
    assert await svc.call(lambda b: "ok") == "ok"


async def test_cancelling_caller_of_disconnect_is_not_swallowed(env: Env) -> None:
    svc = await env.make()

    async def stubborn() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            await asyncio.sleep(0.3)  # slow to die: the outer cancel lands meanwhile

    svc._keepalive_task = asyncio.create_task(stubborn())  # noqa: SLF001
    await asyncio.sleep(0)
    caller = asyncio.create_task(svc.disconnect())
    await asyncio.sleep(0.1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert caller.cancelled()


async def test_status_has_serial_and_last_activity(env: Env) -> None:
    svc = await env.make(connect=False)
    st = svc.status()
    assert st.serial is None and st.last_activity is None
    st = await svc.connect()
    assert st.serial == "?" and st.last_activity is not None
    assert (await svc.disconnect()).last_activity is None


async def test_stop_fails_pending_and_leaks_no_threads(env: Env) -> None:
    svc = await env.make()
    assert worker_threads(svc) == 1
    stuck = asyncio.create_task(svc.call(hang, timeout=5))
    await wait_until(env.backend.entered.is_set)
    queued = asyncio.create_task(svc.call(lambda b: 1, timeout=5))
    await asyncio.sleep(0)
    await svc.stop()
    with pytest.raises(CameraNotConnected):
        await queued
    with pytest.raises(CameraNotConnected):
        await stuck
    env.backend.release.set()  # let the abandoned worker finish and exit
    await wait_until(lambda: worker_threads(svc) == 0)
    assert svc.state == S.DISCONNECTED


# 6. keepalive --------------------------------------------------------------------------
async def test_keepalive_publishes_battery_on_change_only(env: Env) -> None:
    svc = await env.make(keepalive_enabled=True, keepalive_interval_s=0.01)
    await wait_until(lambda: env.backend.battery_reads >= 3)
    assert env.bus.of(EventType.BATTERY) == [{"level": "90%"}]
    env.backend.battery = "80%"
    await wait_until(lambda: len(env.bus.of(EventType.BATTERY)) == 2)
    assert env.bus.of(EventType.BATTERY)[-1] == {"level": "80%"}
    await svc.disconnect()


async def test_keepalive_skipped_in_liveview_and_after_recent_call(env: Env) -> None:
    # Interval far longer than the test: any read below must come from a state/interval bug.
    svc = await env.make(keepalive_enabled=True, keepalive_interval_s=60.0)
    await svc.transition(S.LIVEVIEW)
    await asyncio.sleep(0.1)
    assert env.backend.battery_reads == 0
    await svc.transition(S.IDLE)
    for _ in range(5):
        await svc.call(lambda b: b.get_config("iso"))
    assert env.backend.battery_reads == 0
    env.set_cfg(svc, keepalive_enabled=True, keepalive_interval_s=0.01)  # read live
    await wait_until(lambda: env.backend.battery_reads >= 1)


async def test_keepalive_does_not_queue_behind_inflight_call(env: Env) -> None:
    svc = await env.make()
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    env.set_cfg(svc, keepalive_enabled=True, keepalive_interval_s=0.01)
    await asyncio.sleep(0.3)  # many keepalive cycles
    worker = svc._worker  # noqa: SLF001
    assert worker is not None and worker.queue.qsize() == 0
    assert env.backend.battery_reads == 0
    env.backend.release.set()
    await blocker
    await wait_until(lambda: env.backend.battery_reads >= 1)


async def test_keepalive_interval_read_live(env: Env) -> None:
    svc = await env.make(keepalive_enabled=False, keepalive_interval_s=0.01)
    await asyncio.sleep(0.05)
    assert env.backend.battery_reads == 0
    env.set_cfg(svc, keepalive_enabled=True, keepalive_interval_s=0.01)
    await wait_until(lambda: env.backend.battery_reads >= 1)


async def test_keepalive_failures_disconnect(env: Env) -> None:
    env.backend.fail_battery = RuntimeError("flaky")
    svc = await env.make(keepalive_enabled=True, keepalive_interval_s=0.01)
    await wait_until(lambda: svc.state == S.DISCONNECTED)
    assert env.backend.battery_reads == 3
    assert env.bus.of(EventType.CAMERA_DISCONNECTED)[0]["reason"] == "keepalive failed"


async def test_io_error_disconnects_and_reconnects(env: Env) -> None:
    svc = await env.make(connect_retries=5, reconnect_interval_s=0.01)

    def io(_b: CameraBackend) -> None:
        raise CameraIOError()

    with pytest.raises(CameraIOError):
        await svc.call(io, retry=False)
    assert env.bus.of(EventType.CAMERA_DISCONNECTED)
    await wait_until(lambda: svc.state == S.IDLE)
    assert len(env.bus.of(EventType.CAMERA_CONNECTED)) == 2


async def test_explicit_disconnect_stops_reconnect(env: Env) -> None:
    svc = await env.make(connect_retries=50, reconnect_interval_s=0.01)

    def io(_b: CameraBackend) -> None:
        raise CameraIOError()

    env.backend.fail_open = CameraNotFound()
    with pytest.raises(CameraIOError):
        await svc.call(io)
    await wait_until(lambda: env.factory_calls >= 3)
    await svc.disconnect()
    calls = env.factory_calls
    await asyncio.sleep(0.1)
    assert env.factory_calls == calls and svc.state == S.DISCONNECTED


async def test_call_during_auto_reconnect_waits_then_runs(env: Env) -> None:
    svc = await env.make(connect_retries=50, reconnect_interval_s=0.05)

    def io(_b: CameraBackend) -> None:
        raise CameraIOError()

    env.backend.fail_open = CameraNotFound()
    with pytest.raises(CameraIOError):
        await svc.call(io, retry=False)
    await wait_until(lambda: svc.state == S.DISCONNECTED and env.factory_calls >= 2)
    env.backend.fail_open = None
    assert await svc.call(lambda _b: 7) == 7
    assert svc.state in (S.IDLE, S.BUSY)


async def test_call_after_user_disconnect_fails_immediately(env: Env) -> None:
    svc = await env.make()
    await svc.disconnect()
    with pytest.raises(CameraNotConnected):
        await asyncio.wait_for(svc.call(lambda _b: 7), 1)


# 7. lease ------------------------------------------------------------------------------
async def test_lease_rules(env: Env) -> None:
    svc = await env.make()
    await svc.list_settings()  # warm the cache
    async with svc.lease("timelapse") as lease:
        assert lease.owner == "timelapse" and svc.status().leased_by == "timelapse"
        with pytest.raises(CameraBusy):
            await svc.call(lambda b: 1)
        with pytest.raises(CameraBusy):
            await svc.call(lambda b: 1, owner="other", priority=Priority.CAPTURE)
        with pytest.raises(CameraBusy):
            await svc.capture(timeout=0.02)
        with pytest.raises(CameraBusy):
            await svc.set_setting("iso", "200")
        with pytest.raises(CameraBusy):
            async with svc.lease("second"):
                pass
        assert await svc.call(lambda b: 7, owner="timelapse") == 7
        assert await svc.call(lambda b: 8, priority=Priority.KEEPALIVE) == 8
        assert (await svc.get_setting("iso")).value == "100"
        assert len(await svc.capture(timeout=0.02, owner="timelapse")) >= 1
        await svc.transition(S.LIVEVIEW)
        assert await svc.preview_frame() == b"jpeg"
    assert svc.status().leased_by is None
    assert await svc.call(lambda b: 9) == 9


async def test_lease_released_on_error(env: Env) -> None:
    svc = await env.make()
    with pytest.raises(RuntimeError):
        async with svc.lease("x"):
            raise RuntimeError("boom")
    async with svc.lease("y"):
        pass


# 8. settings cache ---------------------------------------------------------------------
async def test_settings_cache_and_invalidation(env: Env) -> None:
    svc = await env.make()
    first = await svc.list_settings()
    assert await svc.list_settings() is first and env.backend.list_calls == 1
    gets = env.backend.get_calls
    assert (await svc.get_setting("iso")).value == "100"
    assert env.backend.get_calls == gets  # served from the cache
    await svc.list_settings(refresh=True)
    assert env.backend.list_calls == 2
    widget = await svc.set_setting("iso", "400")
    assert widget.value == "400"
    changed = [e for e in env.bus.of(EventType.SETTING_CHANGED) if e["name"] == "iso"]
    assert changed == [{"name": "iso", "value": "400"}]
    assert (await svc.get_setting("iso")).value == "400"
    assert env.backend.list_calls == 2  # one widget updated in place, no tree refetch
    tree_iso = next(w for w in (await svc.list_settings())[0].children if w.name == "iso")
    assert tree_iso.value == "400"  # the cached tree reflects the write too
    await svc.set_setting("imagequality", "x")  # mode-like: may change other widgets' choices
    await svc.get_setting("iso")
    assert env.backend.list_calls == 3
    await svc.disconnect()
    await svc.connect()
    await svc.get_setting("iso")
    assert env.backend.list_calls == 4  # and by disconnect


# 9. capture ----------------------------------------------------------------------------
async def test_capture_collects_raw_and_jpeg_without_sleeping(env: Env) -> None:
    svc = await env.make()
    env.backend.on_capture.extend(
        [
            CameraEvent(CamEvent.FILE_ADDED, file=A_NEF),
            CameraEvent(CamEvent.FILE_ADDED, file=A_JPG),
            CameraEvent(CamEvent.CAPTURE_COMPLETE),
        ]
    )
    t0 = time.monotonic()
    files = await svc.capture(timeout=5)
    assert time.monotonic() - t0 < 1
    assert files == [A_NEF, A_JPG]
    assert env.bus.of(EventType.CAPTURE_STARTED) == [{}]
    assert env.bus.of(EventType.CAPTURE_COMPLETE) == [
        {"files": [{"folder": f.folder, "name": f.name} for f in files]}
    ]
    assert svc.state == S.IDLE


async def test_capture_ends_on_quiet_window_when_camera_swallowed_complete(env: Env) -> None:
    svc = await env.make(quiet=0.05)
    env.backend.on_capture.append(CameraEvent(CamEvent.FILE_ADDED, file=A_JPG))
    t0 = time.monotonic()
    files = await svc.capture(timeout=60)  # must not wait for the 60 s timeout
    assert time.monotonic() - t0 < 30
    assert files == [A_NEF, A_JPG] and svc.state == S.IDLE


async def test_capture_drops_events_queued_before_it(env: Env) -> None:
    svc = await env.make(quiet=0.05)
    env.backend.events.append(CameraEvent(CamEvent.FILE_ADDED, file=A_JPG))  # stray body shot
    assert await svc.capture(timeout=60) == [A_NEF]


async def test_capture_dedupes_returned_path_with_file_added(env: Env) -> None:
    svc = await env.make()
    env.backend.on_capture.append(CameraEvent(CamEvent.FILE_ADDED, file=A_NEF))
    assert await svc.capture(timeout=60) == [A_NEF]


async def test_capture_complete_event_ends_drain_before_quiet_window(env: Env) -> None:
    svc = await env.make(quiet=60.0)
    env.backend.on_capture.extend(
        [CameraEvent(CamEvent.FILE_ADDED, file=A_JPG), CameraEvent(CamEvent.CAPTURE_COMPLETE)]
    )
    t0 = time.monotonic()
    assert await svc.capture(timeout=60) == [A_NEF, A_JPG]
    assert time.monotonic() - t0 < 30


async def test_capture_io_error_leaves_disconnected(env: Env) -> None:
    svc = await env.make()
    env.backend.capture = lambda: (_ for _ in ()).throw(CameraIOError())  # type: ignore[method-assign]
    with pytest.raises(CameraIOError):
        await svc.capture(timeout=1)
    assert svc.state == S.DISCONNECTED


async def test_refresh_setting_is_one_get_config_not_a_tree_read(env: Env) -> None:
    svc = await env.make()
    await svc.list_settings()
    env.backend.values["iso"] = "800"  # changed on the camera body
    assert (await svc.refresh_setting("iso")).value == "800"
    assert (await svc.get_setting("iso")).value == "800"
    assert env.backend.list_calls == 1


async def test_leaving_liveview_for_idle_ends_preview_even_under_other_lease(env: Env) -> None:
    svc = await env.make()
    await svc.transition(S.LIVEVIEW)
    async with svc.lease("timelapse"):
        await svc.transition(S.IDLE)
    assert env.backend.end_previews == 1


async def test_capture_invalidates_preview_state_regression(env: Env) -> None:
    svc = await env.make()
    await svc.transition(S.LIVEVIEW)
    await svc.capture(timeout=0.02)
    assert env.backend.invalidations == 1 and svc.state == S.LIVEVIEW


async def test_connect_fails_and_abandons_worker_when_exposure_read_hangs(env: Env) -> None:
    svc = await env.make(connect=False)
    real = env.backend.get_config

    def get_config(name: str) -> ConfigWidget:
        if name in ("expprogram", "autoexposuremode"):
            return real("hang")
        return real(name)

    env.backend.get_config = get_config  # type: ignore[method-assign]
    svc._read_exposure_timeout_s = 0.05  # noqa: SLF001
    with pytest.raises(CameraTimeout):
        await svc.connect()
    assert svc.state == S.DISCONNECTED
    env.backend.release.set()
    env.backend.get_config = real  # type: ignore[method-assign]
    assert (await svc.connect()).state == S.IDLE


async def test_cancelled_connect_during_exposure_read_returns_to_disconnected(env: Env) -> None:
    svc = await env.make(connect=False)
    real = env.backend.get_config

    def get_config(name: str) -> ConfigWidget:
        if name in ("expprogram", "autoexposuremode"):
            return real("hang")
        return real(name)

    env.backend.get_config = get_config  # type: ignore[method-assign]
    task = asyncio.create_task(svc.connect())
    await wait_until(env.backend.entered.is_set)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert svc.state == S.DISCONNECTED
    env.backend.release.set()


async def test_bulb_precheck_uses_fresh_cache_and_reads_when_stale(env: Env) -> None:
    svc = await env.make()
    env.backend.values["shutterspeed"] = "1/250"
    await svc.get_setting("shutterspeed")
    await svc.get_setting("capturetarget")
    before = env.backend.get_calls
    await svc.capture()
    assert env.backend.get_calls == before  # cached non-bulb: no extra read
    svc.invalidate_settings()
    await svc.capture()
    assert env.backend.get_calls == before + 2  # shutterspeed + capturetarget
    env.backend.values["shutterspeed"] = "Bulb"
    svc.invalidate_settings()
    with pytest.raises(InvalidState):
        await svc.capture()


async def test_bulb_precheck_timeout_propagates(env: Env) -> None:
    svc = await env.make()
    real = env.backend.get_config

    def get_config(name: str) -> ConfigWidget:
        return real("hang") if name == "shutterspeed" else real(name)

    env.backend.get_config = get_config  # type: ignore[method-assign]
    svc._refuse_bulb_timeout_s = 0.05  # noqa: SLF001
    with pytest.raises(CameraTimeout):
        await svc.capture()
    env.backend.release.set()


def test_dedupe_reads_sizes_only_for_cross_root_pairs() -> None:
    from backend.core.camera_service import dedupe_slot_copies

    sized: list[str] = []

    class B:
        def file_info(self, folder: str, name: str) -> Any:
            sized.append(f"{folder}/{name}")
            return type("I", (), {"size": 10})()

    files = [
        CameraFilePath("/store_00010001/DCIM/100", "A.NEF"),
        CameraFilePath("/store_00020001/DCIM/100", "A.NEF"),
        CameraFilePath("/store_00010001/DCIM/100", "B.NEF"),
    ]
    kept = dedupe_slot_copies(cast(CameraBackend, B()), files)
    assert kept == [files[0], files[2]]
    assert sorted(sized) == sorted(f"{f.folder}/{f.name}" for f in files[:2])


async def test_capture_io_error_after_shutter_is_not_retried(env: Env) -> None:
    svc = await env.make(connect_retries=5, reconnect_interval_s=0.01)
    shots = 0

    def boom() -> CameraFilePath:
        nonlocal shots
        shots += 1
        raise CameraIOError()

    env.backend.capture = boom  # type: ignore[method-assign]
    with pytest.raises(CameraIOError):
        await svc.capture(timeout=1)
    await asyncio.sleep(0.2)
    assert shots == 1


async def test_error_under_lease_postpones_recovery_until_release(env: Env) -> None:
    svc = await env.make(connect_retries=5, reconnect_interval_s=0.01)
    svc._stuck_grace_s = 0.05  # noqa: SLF001
    async with svc.lease("bulb"):
        await svc.transition(S.ERROR)
        await asyncio.sleep(0.3)  # several grace periods: no watchdog may fire
        assert svc.state == S.ERROR
        assert svc.status().leased_by == "bulb"
        assert env.bus.of(EventType.CAMERA_DISCONNECTED) == []
    await wait_until(lambda: svc.state == S.IDLE)
    assert env.bus.of(EventType.CAMERA_DISCONNECTED)  # recovery reconnected after release


async def test_card_check_caches_only_ok_storage(env: Env) -> None:
    svc = await env.make()
    await svc.set_setting("capturetarget", "Memory card")
    env.backend.storage = []
    assert type(await svc.card_problem()).__name__ == "NoCard"
    env.backend.storage = [StorageInfo("SD", "/store", 100, 50, 10, "rw")]
    assert await svc.card_problem() is None  # just-inserted card works at once
    env.backend.storage = []
    assert await svc.card_problem() is None  # OK result stays cached


@pytest.mark.parametrize(("access", "locked"), [("ro", True), ("ro_delete", False), ("rw", False)])
async def test_card_problem_only_ro_is_locked(env: Env, access: str, locked: bool) -> None:
    svc = await env.make()
    await svc.set_setting("capturetarget", "Memory card")
    env.backend.storage = [StorageInfo("SD", "/store", 100, 50, 10, access)]
    problem = await svc.card_problem(fresh=True)
    assert (type(problem).__name__ == "CardLocked") if locked else problem is None


# review fixes ---------------------------------------------------------------------------
async def test_preview_does_not_drain_events_while_recording_or_leased(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.core.camera_service._PREVIEW_EVENT_S", 0.0)
    svc = await env.make()
    await svc.transition(S.LIVEVIEW)
    clip = CameraEvent(CamEvent.FILE_ADDED, A_NEF)
    env.backend.events.append(clip)
    async with svc.lease("recording"):
        await svc.preview_frame()
        assert list(env.backend.events) == [clip]  # the lease holder's watcher keeps it
    await svc.transition(S.RECORDING)
    await svc.preview_frame()
    assert list(env.backend.events) == [clip]
    assert not svc.stray_files


async def test_event_poll_does_not_count_as_activity_so_keepalive_runs(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.core.camera_service._EVENT_POLL_S", 0.01)
    await env.make(keepalive_enabled=True, keepalive_interval_s=0.1)
    await wait_until(lambda: env.backend.battery_reads >= 2)


async def test_event_poll_repeated_failures_are_a_lost_link(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("backend.core.camera_service._EVENT_POLL_S", 0.01)
    svc = await env.make(connect_retries=0, reconnect_interval_s=60.0)
    env.backend.fail_events = RuntimeError("wedged")
    await wait_until(lambda: svc.state == S.DISCONNECTED)
    assert env.bus.of(EventType.CAMERA_DISCONNECTED)[0]["reason"] == "event poll failed"


async def test_connect_cancels_previous_background_tasks(env: Env) -> None:
    svc = await env.make()
    old_events, old_keep = svc._event_task, svc._keepalive_task  # noqa: SLF001
    assert old_events is not None
    svc._try_state(S.DISCONNECTED)  # noqa: SLF001 - as a connect() from ERROR would find it
    await svc._do_connect()  # noqa: SLF001
    assert old_events.done() and old_keep is not None and old_keep.done()
    assert svc._event_task is not old_events  # noqa: SLF001


async def test_refresh_setting_shared_coalesces_concurrent_and_recent_reads(env: Env) -> None:
    svc = await env.make()
    before = env.backend.get_calls
    results = await asyncio.gather(*(svc.refresh_setting_shared("iso") for _ in range(4)))
    assert sum(performed for _, performed in results) == 1
    await svc.refresh_setting_shared("iso")  # within the TTL, nothing changed since
    assert env.backend.get_calls == before + 1


# A-series review fixes ------------------------------------------------------------------
async def test_reconnect_turns_persistent_when_camera_not_found(env: Env) -> None:
    svc = await env.make(connect_retries=1, reconnect_interval_s=0.01)

    def io(_b: CameraBackend) -> None:
        raise CameraIOError()

    env.backend.fail_open = CameraNotFound()
    with pytest.raises(CameraIOError):
        await svc.call(io, retry=False)
    await wait_until(lambda: env.factory_calls >= 5)  # well past connect_retries
    env.backend.fail_open = None
    await wait_until(lambda: svc.state == S.IDLE)


async def test_connect_from_error_failing_in_zombie_wait_self_resolves(env: Env) -> None:
    svc = await env.make(connect_retries=5, reconnect_interval_s=0.01)
    blocker = asyncio.create_task(svc.call(hang, timeout=30))
    await wait_until(env.backend.entered.is_set)
    await svc.disconnect()
    with pytest.raises(CameraNotConnected):
        await blocker
    svc._zombie_wait_s = 0.05  # noqa: SLF001
    svc._try_state(S.ERROR)  # noqa: SLF001
    with pytest.raises(CameraTimeout):
        await svc.connect()
    assert svc.state == S.DISCONNECTED
    env.backend.release.set()
    await wait_until(lambda: svc.state == S.IDLE)


async def test_raising_connect_hook_does_not_leave_connecting(env: Env) -> None:
    svc = await env.make(connect=False)

    def boom() -> None:
        raise RuntimeError("hook")

    svc.connect_hooks.append(boom)
    with pytest.raises(RuntimeError):
        await svc.connect()
    assert svc.state == S.DISCONNECTED


async def test_reconnecting_counts_connecting_state(env: Env) -> None:
    svc = await env.make(connect_retries=5, reconnect_interval_s=60.0)
    await svc.disconnect()
    svc._start_reconnect()  # noqa: SLF001
    svc._set_state(S.CONNECTING)  # noqa: SLF001
    assert svc._reconnecting()  # noqa: SLF001


async def test_unreported_free_images_does_not_block_card(env: Env) -> None:
    svc = await env.make()
    await svc.set_setting("capturetarget", "Memory card")
    env.backend.storage = [StorageInfo("SD", "/store", 100, 50, None, "rw")]  # type: ignore[arg-type]
    assert await svc.card_problem(fresh=True) is None


async def test_list_settings_concurrent_callers_share_one_read(env: Env) -> None:
    svc = await env.make()
    svc.invalidate_settings()
    env.backend.list_calls = 0
    await asyncio.gather(*(svc.list_settings() for _ in range(5)))
    assert env.backend.list_calls == 1


async def test_explain_failure_keeps_camera_error_and_adds_card_facts(env: Env) -> None:
    svc = await env.make()
    await svc.set_setting("capturetarget", "Memory card")
    env.backend.storage = []
    exc = CameraOperationFailed("Camera says X", details={"gphoto2_error": "-1"})
    await svc.explain_failure(exc)  # no relabelling: the original is what gets re-raised
    assert type(exc) is CameraOperationFailed and exc.message == "Camera says X"
    assert exc.details["gphoto2_error"] == "-1"
    assert exc.details["card"] == {"cards": 0, "writable": 0, "free_images": None}


async def test_refresh_waits_for_inflight_read_then_reads_again(env: Env) -> None:
    svc = await env.make()
    svc.invalidate_settings()
    env.backend.list_calls = 0
    first = asyncio.create_task(svc.list_settings())
    await asyncio.sleep(0)  # the first read is now in flight
    await svc.list_settings(refresh=True)
    await first
    assert env.backend.list_calls == 2


async def test_orphaned_failed_tree_read_is_not_reported_as_unretrieved(env: Env) -> None:
    """The only awaiting caller is cancelled in the very loop turn the read fails: the shield
    drops the exception, so list_settings must mark it retrieved itself."""
    import gc

    svc = await env.make()
    svc.invalidate_settings()
    loop = asyncio.get_running_loop()
    reported: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _l, ctx: reported.append(ctx))
    caller: asyncio.Task[Any] | None = None

    async def failing_read() -> list[ConfigWidget]:
        assert caller is not None
        loop.call_soon(caller.cancel)  # runs before the task's done callbacks
        raise CameraOperationFailed("read failed")

    svc._read_tree = failing_read  # type: ignore[method-assign]  # noqa: SLF001
    caller = asyncio.create_task(svc.list_settings())
    with pytest.raises(asyncio.CancelledError):
        await caller
    await asyncio.sleep(0.05)
    svc._tree_task = None  # noqa: SLF001
    gc.collect()
    await asyncio.sleep(0)
    assert not [c for c in reported if "never retrieved" in str(c.get("message"))]
