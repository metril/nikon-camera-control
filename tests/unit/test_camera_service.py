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
)
from backend.camera.backend import EventType as CamEvent
from backend.core.camera_service import CameraService, Priority
from backend.core.config_store import AppConfig, CameraConfig, ConfigStore
from backend.core.errors import (
    CameraBusy,
    CameraIOError,
    CameraNotConnected,
    CameraNotFound,
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
        self._open = False
        self.fail_open: Exception | None = None
        self.fail_battery: Exception | None = None
        self.battery: str = "90%"
        self.battery_reads = 0
        self.list_calls = 0
        self.get_calls = 0
        self.preview_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.events: collections.deque[CameraEvent] = collections.deque()
        self.values = {"iso": "100", "aperture": "5.6"}

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
        return A_NEF

    def wait_for_event(self, timeout_s: float) -> CameraEvent:
        if self.events:
            return self.events.popleft()
        time.sleep(min(timeout_s, 0.005))
        return CameraEvent(CamEvent.TIMEOUT)

    def capture_preview(self) -> bytes:
        self.preview_calls += 1
        return b"jpeg"

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

    async def make(self, *, connect: bool = True, **cam: Any) -> CameraService:
        cam.setdefault("keepalive_enabled", False)
        cam.setdefault("connect_retries", 0)
        cfg = AppConfig.model_construct(camera=CameraConfig.model_construct(**cam))
        store = ConfigStore(self.tmp / "config.json", initial=cfg)
        svc = CameraService(self._factory, store, cast(EventBus, self.bus))
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


async def wait_until(pred: Callable[[], bool], timeout: float = 2.0) -> None:  # noqa: ASYNC109
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.002)


def hang(b: CameraBackend) -> Any:
    return b.get_config("hang")


def worker_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == "camera-worker" and t.is_alive())


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
    base = worker_threads()
    stuck = asyncio.create_task(svc.call(hang, timeout=0.05))
    await wait_until(env.backend.entered.is_set)
    queued = asyncio.create_task(svc.call(lambda b: "late", timeout=5))
    await asyncio.sleep(0)
    with pytest.raises(CameraTimeout):
        await stuck
    with pytest.raises(CameraTimeout):
        await queued
    assert svc.state == S.ERROR
    assert worker_threads() == base == 1
    assert env.backend.closes == 0  # reset only after the stuck call returns
    env.backend.release.set()
    await wait_until(lambda: svc.state == S.IDLE)
    assert (env.backend.opens, env.backend.closes) == (2, 1)
    assert worker_threads() == 1
    assert await svc.call(lambda b: "ok") == "ok"


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


async def test_stop_fails_pending_and_leaks_no_threads(env: Env) -> None:
    base = threading.active_count()
    svc = await env.make()
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
    await wait_until(lambda: threading.active_count() == base)
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
    svc = await env.make(keepalive_enabled=True, keepalive_interval_s=0.04)
    await svc.transition(S.LIVEVIEW)
    await asyncio.sleep(0.1)
    assert env.backend.battery_reads == 0
    await svc.transition(S.IDLE)
    end = time.monotonic() + 0.1  # calls faster than the interval keep it quiet
    while time.monotonic() < end:
        await svc.call(lambda b: b.get_config("iso"))
        await asyncio.sleep(0.01)
    assert env.backend.battery_reads == 0
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
        await svc.call(io)
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
    assert env.bus.of(EventType.SETTING_CHANGED) == [{"name": "iso", "value": "400"}]
    assert (await svc.get_setting("iso")).value == "400"
    assert env.backend.list_calls == 3  # cache was invalidated by set_setting
    await svc.disconnect()
    await svc.connect()
    await svc.get_setting("iso")
    assert env.backend.list_calls == 4  # and by disconnect


# 9. capture ----------------------------------------------------------------------------
async def test_capture_collects_raw_and_jpeg_without_sleeping(env: Env) -> None:
    svc = await env.make()
    env.backend.events.extend(
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


async def test_capture_without_complete_event_returns_after_timeout(env: Env) -> None:
    svc = await env.make()
    files = await svc.capture(timeout=0.05)
    assert files == [A_NEF] and svc.state == S.IDLE


async def test_capture_io_error_leaves_disconnected(env: Env) -> None:
    svc = await env.make()
    env.backend.capture = lambda: (_ for _ in ()).throw(CameraIOError())  # type: ignore[method-assign]
    with pytest.raises(CameraIOError):
        await svc.capture(timeout=1)
    assert svc.state == S.DISCONNECTED
