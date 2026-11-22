"""LiveViewService against a real CameraService over FakeCamera."""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from PIL import Image

from backend.api.schemas.common import EventType
from backend.camera.fake import FakeCamera
from backend.core.camera_service import CameraService
from backend.core.config_store import AppConfig, ConfigStore
from backend.core.events import EventBus
from backend.core.state import CameraState as S
from backend.services.liveview import LiveViewService, process_frame

Factory = Callable[[], FakeCamera]


async def until(pred: Callable[[], bool], limit: float = 3.0) -> None:
    deadline = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.01)


class Rig:
    def __init__(self, tmp: Path, factory: Factory) -> None:
        cfg = AppConfig.model_validate({"camera": {"keepalive_interval_s": 5.0}})
        self.store = ConfigStore(tmp / "c.json", initial=cfg)
        self.bus = EventBus()
        self.cam = CameraService(factory, self.store, self.bus, event_quiet_window_s=0.01)
        self.lv = LiveViewService(self.cam, self.bus, self.store, interval_s=0.005)


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Rig]:
    fake = FakeCamera()
    r = Rig(tmp_path, lambda: fake)
    r.fake = fake  # type: ignore[attr-defined]
    await r.cam.start()
    await r.cam.connect()
    yield r
    await r.lv.aclose()
    await r.cam.stop()


async def test_slow_subscriber_does_not_block_fast_and_mailbox_is_one_slot(rig: Rig) -> None:
    slow, fast = rig.lv.subscribe(), rig.lv.subscribe()
    got = 0
    while got < 8:
        item = await asyncio.wait_for(fast.get(), 2)
        got += bool(item and item[0] == "frame")
    assert slow.frames_dropped > 0
    assert slow._frame is not None  # exactly one latest frame held, memory does not grow
    rig.lv.unsubscribe(slow)
    rig.lv.unsubscribe(fast)


async def test_one_producer_for_many_subscribers(rig: Rig) -> None:
    subs = [rig.lv.subscribe() for _ in range(3)]
    for s in subs:
        while (await asyncio.wait_for(s.get(), 2))[0] != "frame":  # type: ignore[index]
            pass
    st = rig.lv.stats()
    calls = rig.fake.calls["capture_preview"]  # type: ignore[attr-defined]
    assert calls <= st.frames_produced + 1  # not multiplied by subscriber count
    for s in subs:
        rig.lv.unsubscribe(s)


async def test_last_subscriber_leaving_returns_camera_to_idle(rig: Rig) -> None:
    sub = rig.lv.subscribe()
    await until(lambda: rig.cam.state == S.LIVEVIEW)
    rig.lv.unsubscribe(sub)
    await until(lambda: rig.cam.state == S.IDLE and not rig.lv.running)


async def test_sticky_start_survives_subscriber_and_stop_releases(rig: Rig) -> None:
    await rig.lv.start()
    sub = rig.lv.subscribe()
    rig.lv.unsubscribe(sub)
    await asyncio.sleep(0.05)
    assert rig.lv.running and rig.cam.state == S.LIVEVIEW
    await rig.lv.stop()
    assert not rig.lv.running and rig.cam.state == S.IDLE


async def test_disconnect_makes_inactive_and_reconnect_resumes_without_stale_backend(
    tmp_path: Path,
) -> None:
    """Regression: handler kept a stale camera object after reconnect / _active stayed True."""
    made: list[FakeCamera] = []

    def factory() -> FakeCamera:
        made.append(FakeCamera())
        return made[-1]

    r = Rig(tmp_path, factory)
    await r.cam.start()
    await r.cam.connect()
    sub = r.lv.subscribe()
    await until(lambda: r.lv.stats().active)
    await r.cam.disconnect()
    await until(lambda: not r.lv.stats().active)
    assert r.lv.stats().reason == "camera_disconnected" and r.lv.running
    await r.cam.connect()
    await until(lambda: r.lv.stats().active)
    assert len(made) == 2 and made[1].calls.get("capture_preview", 0) > 0
    r.lv.unsubscribe(sub)
    await r.lv.aclose()
    await r.cam.stop()


async def test_recording_pauses_then_resumes_without_swallowed_error(rig: Rig) -> None:
    sub = rig.lv.subscribe()
    await until(lambda: rig.cam.state == S.LIVEVIEW)
    await rig.cam.transition(S.RECORDING)
    await until(lambda: rig.lv.stats().reason == "camera_recording")
    assert rig.lv.running and not rig.lv.stats().active
    await rig.cam.transition(S.LIVEVIEW)
    await until(lambda: rig.lv.stats().active)
    rig.lv.unsubscribe(sub)


async def test_events_published(rig: Rig) -> None:
    ev = rig.bus.subscribe()
    await rig.lv.start()
    await rig.lv.stop()
    seen: list[EventType] = []
    while EventType.LIVEVIEW_STOPPED not in seen:
        seen.append((await asyncio.wait_for(ev.__anext__(), 2)).type)
    assert EventType.LIVEVIEW_STARTED in seen
    ev.close()


async def test_aclose_wakes_subscribers(rig: Rig) -> None:
    sub = rig.lv.subscribe()
    await rig.lv.aclose()
    while (item := await asyncio.wait_for(sub.get(), 2)) is not None:
        pass
    assert item is None and not rig.lv.running and rig.cam.state == S.IDLE


def _jpeg(width: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, width // 2), (10, 20, 30)).save(buf, "JPEG")
    return buf.getvalue()


def test_process_frame_skips_when_not_needed_and_downscales_when_wider() -> None:
    small = _jpeg(320)
    assert process_frame(small, 640, 70) is small
    assert process_frame(small, None, 70) is small
    out = process_frame(_jpeg(2000), 640, 70)
    assert Image.open(io.BytesIO(out)).width == 640
    assert process_frame(b"not a jpeg", 640, 70) == b"not a jpeg"
