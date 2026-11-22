"""Real CameraService + real EventBus + FakeCamera (no HTTP)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import pytest

from backend.api.schemas.common import Event
from backend.camera.fake import FakeCamera
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import CameraBusy, CameraTimeout
from backend.core.events import EventBus, Subscription
from backend.core.state import CameraState


@pytest.fixture
async def bus() -> AsyncIterator[EventBus]:
    b = EventBus()
    b.bind_loop(asyncio.get_running_loop())
    yield b
    b.close()


@pytest.fixture
async def svc(
    config_store: ConfigStore, fake_camera: FakeCamera, bus: EventBus
) -> AsyncIterator[CameraService]:
    config_store.update({"camera": {"connect_retries": 20, "reconnect_interval_s": 0.5}})
    s = CameraService(lambda: fake_camera, config_store, bus)
    await s.start()
    yield s
    fake_camera.release_all()
    await s.stop()


async def until(pred: Callable[[], bool], timeout: float = 5.0) -> None:  # noqa: ASYNC109
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


def drain(sub: Subscription) -> list[Event]:
    out: list[Event] = []
    while not sub._queue.empty():
        item = sub._queue.get_nowait()
        if item is not None:
            out.append(item)
    return out


async def test_connect_publishes_events(svc: CameraService, bus: EventBus) -> None:
    sub = bus.subscribe()
    st = await svc.connect()
    assert st.state == CameraState.IDLE and st.model == "Nikon DSC D500"
    await asyncio.sleep(0.05)
    evs = drain(sub)
    types = [e.type.value for e in evs]
    assert types[:2] == ["camera_state", "camera_state"] and "camera_connected" in types
    states = [e.data["state"] for e in evs if e.type.value == "camera_state"]
    assert states == ["connecting", "idle"]
    await svc.disconnect()
    await asyncio.sleep(0.05)
    assert "camera_disconnected" in [e.type.value for e in drain(sub)]
    sub.close()


@pytest.mark.parametrize(
    ("quality", "exts"),
    [
        ("JPEG Fine", {".JPG"}),
        ("JPEG Basic", {".JPG"}),
        ("NEF (Raw)", {".NEF"}),
        ("NEF+JPEG Fine", {".NEF", ".JPG"}),
        ("NEF+JPEG Basic", {".NEF", ".JPG"}),
    ],
)
async def test_capture_each_quality(
    svc: CameraService, bus: EventBus, quality: str, exts: set[str]
) -> None:
    await svc.connect()
    await svc.set_setting("imagequality", quality)
    sub = bus.subscribe()
    t0 = time.monotonic()
    files = await svc.capture()
    elapsed = time.monotonic() - t0
    assert {f.name[f.name.rindex(".") :] for f in files} == exts
    assert len(files) == len(exts)
    assert elapsed < 0.5, "capture must end on CAPTURE_COMPLETE, not the full timeout"
    assert svc.state == CameraState.IDLE
    await asyncio.sleep(0.05)
    types = [e.type.value for e in drain(sub)]
    assert "capture_started" in types and "capture_complete" in types
    sub.close()


async def test_hang_timeout_error_then_recovery(
    svc: CameraService, fake_camera: FakeCamera, bus: EventBus
) -> None:
    await svc.connect()
    sub = bus.subscribe()
    fake_camera.hang("summary")
    with pytest.raises(CameraTimeout):
        await svc.call(lambda b: b.summary(), timeout=0.2)
    assert svc.state == CameraState.ERROR
    fake_camera.release_all()
    await until(lambda: svc.state == CameraState.IDLE)
    assert (await svc.call(lambda b: b.summary())).startswith("Manufacturer")
    states = [e.data["state"] for e in drain(sub) if e.type.value == "camera_state"]
    assert states[:2] == ["error", "idle"]
    sub.close()


async def test_unplug_disconnects_then_replug_reconnects(
    svc: CameraService, fake_camera: FakeCamera, bus: EventBus
) -> None:
    await svc.connect()
    sub = bus.subscribe()
    fake_camera.unplug()
    with pytest.raises(Exception, match="unplugged"):
        await svc.call(lambda b: b.summary())
    assert svc.state == CameraState.DISCONNECTED
    await asyncio.sleep(0.8)  # at least one failed reconnect attempt
    assert svc.state == CameraState.DISCONNECTED
    fake_camera.replug()
    await until(lambda: svc.state == CameraState.IDLE, timeout=8.0)
    types = [e.type.value for e in drain(sub)]
    assert "camera_disconnected" in types and "camera_connected" in types
    sub.close()


async def test_lease_exclusion(svc: CameraService) -> None:
    await svc.connect()
    async with svc.lease("timelapse") as lease:
        assert lease.owner == "timelapse" and svc.status().leased_by == "timelapse"
        with pytest.raises(CameraBusy):
            await svc.capture()
        with pytest.raises(CameraBusy):
            await svc.set_setting("iso", "400")
        with pytest.raises(CameraBusy):
            async with svc.lease("other"):
                pass
        assert len(await svc.capture(owner="timelapse")) >= 1
        assert (await svc.get_setting("iso")).name == "iso"  # reads allowed
    assert svc.status().leased_by is None
    assert len(await svc.capture()) >= 1


async def test_settings_cache_hits_backend_once(
    svc: CameraService, fake_camera: FakeCamera
) -> None:
    await svc.connect()
    base = fake_camera.calls
    await svc.list_settings()
    for _ in range(5):
        await svc.list_settings()
        await svc.get_setting("iso")
        await svc.get_setting("f-number")
    after = fake_camera.calls
    assert after.get("list_config", 0) - base.get("list_config", 0) == 1
    assert after.get("get_config", 0) == base.get("get_config", 0)
    await svc.list_settings(refresh=True)
    assert fake_camera.calls["list_config"] - base.get("list_config", 0) == 2


async def test_set_setting_invalidates_cache_and_publishes(
    svc: CameraService, fake_camera: FakeCamera, bus: EventBus
) -> None:
    await svc.connect()
    await svc.list_settings()
    sub = bus.subscribe()
    w = await svc.set_setting("iso", "800")
    assert w.value == "800"
    assert (await svc.get_setting("iso")).value == "800"
    await asyncio.sleep(0.05)
    changed = [e for e in drain(sub) if e.type.value == "setting_changed"]
    assert changed and changed[0].data == {"name": "iso", "value": "800"}
    sub.close()
