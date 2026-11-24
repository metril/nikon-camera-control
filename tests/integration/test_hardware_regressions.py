"""Regressions from the first real D500 run, each emulated by a FakeCamera option."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from backend.camera.fake import FakeCamera
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import CameraOperationFailed, CameraTimeout, SettingNotFound
from backend.core.events import EventBus
from backend.core.state import CameraState
from backend.services.settings import SettingsService


@pytest.fixture
async def bus() -> AsyncIterator[EventBus]:
    b = EventBus()
    b.bind_loop(asyncio.get_running_loop())
    yield b
    b.close()


Make = Callable[..., Any]


@pytest.fixture
async def make(config_store: ConfigStore, bus: EventBus) -> AsyncIterator[Make]:
    config_store.update(
        {"camera": {"connect_retries": 20, "reconnect_interval_s": 0.5, "connect_timeout_s": 1.0}}
    )
    made: list[tuple[CameraService, FakeCamera]] = []

    async def _make(fake: FakeCamera, *, connect: bool = True, **kw: Any) -> CameraService:
        kw.setdefault("event_quiet_window_s", 0.05)
        s = CameraService(fake.clone, config_store, bus, **kw)
        made.append((s, fake))
        await s.start()
        if connect:
            await s.connect()
        return s

    yield _make
    for s, f in made:
        f.release_all()
        await s.stop()


async def until(pred: Callable[[], bool], timeout: float = 8.0) -> None:  # noqa: ASYNC109
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.02)


# 1. per-body setting names -------------------------------------------------------------
async def test_d500_setting_aliases(make: Make) -> None:
    svc = await make(FakeCamera(d500_names=True))
    s = SettingsService(svc)
    common = {v.name: v for v in await s.list_settings()}
    assert {"autoexposuremode", "meteringmode"} <= set(common)
    assert common["autoexposuremode"].path.endswith("/expprogram")
    assert (await s.get("meteringmode")).value == "Matrix"
    assert (await s.set("autoexposuremode", "A")).value == "A"
    res = await s.set_many({"meteringmode": "Spot", "autoexposuremode": "S"})
    assert {v.name for v in res.applied} == {"exposuremetermode", "expprogram"}
    assert (await s.get("expprogram")).value == "S"  # the real name works too
    with pytest.raises(SettingNotFound):
        await s.get("drivemode")  # no candidate exists on this body


async def test_other_bodies_keep_their_own_names(make: Make) -> None:
    svc = await make(FakeCamera())
    s = SettingsService(svc)
    assert (await s.get("meteringmode")).path.endswith("/meteringmode")
    assert (await s.set("autoexposuremode", "Program")).value == "Program"


# 2. shutter speed off by a third -------------------------------------------------------
async def test_shutter_shift_is_compensated_and_verified(make: Make) -> None:
    svc = await make(FakeCamera(shutter_shift=True))
    for want in ("1/250", "2", "1/60", "1/8000", "Bulb"):
        assert (await svc.set_setting("shutterspeed", want)).value == want


async def test_unfixable_mismatch_is_an_error(make: Make) -> None:
    class Stuck(FakeCamera):
        def set_config(self, name: str, value: Any) -> None:
            if name == "shutterspeed":
                value = "1/1000"  # camera ignores the request
            super().set_config(name, value)

    svc = await make(Stuck())
    with pytest.raises(CameraOperationFailed) as ei:
        await svc.set_setting("shutterspeed", "1/250")
    assert ei.value.details["requested"] == "1/250" and ei.value.details["actual"] == "1/1000"


# 3. card capture ------------------------------------------------------------------------
async def test_card_capture_is_fast_despite_event_chatter_and_slot2_copies(make: Make) -> None:
    fake = FakeCamera(event_chatter=True, slot2_backup=True)
    svc = await make(fake)
    files = await svc.capture(timeout=30)
    assert fake.calls["wait_for_event"] < 100  # not 30 s worth of chatter
    assert [f.name for f in files] == ["DSC_0001.JPG"]  # the _1 backup copy is dropped
    assert "DSC_0001_1.JPG" in fake._files["/store_00010001/DCIM/100ND500"]  # stays on the card
    await svc.set_setting("imagequality", "NEF+JPEG Fine")
    files = await svc.capture(timeout=30)
    assert sorted(f.name for f in files) == ["DSC_0002.JPG", "DSC_0002.NEF"]


async def test_quiet_window_follows_the_config_live(make: Make, config_store: ConfigStore) -> None:
    svc = await make(FakeCamera(), event_quiet_window_s=None)
    config_store.update({"camera": {"event_quiet_window_s": 0.3}})
    assert svc._quiet_window_s == 0.3
    config_store.update({"camera": {"event_quiet_window_s": 0.1}})
    assert svc._quiet_window_s == 0.1


# 8. recovery ----------------------------------------------------------------------------
async def test_hung_call_recovers_by_itself(make: Make) -> None:
    fake = FakeCamera()
    svc = await make(fake, stuck_grace_s=0.1, zombie_wait_s=0.5)
    async with svc.lease("job"):
        fake.hang("capture")
        with pytest.raises(CameraTimeout):
            await svc.call(lambda b: b.capture(), timeout=0.1, owner="job")
        assert svc.state == CameraState.ERROR
        # the watchdog gives up on the stuck worker, drops the lease and reconnects
        await until(lambda: svc.status().leased_by is None)
    await until(lambda: svc.state == CameraState.IDLE)
    assert fake.calls.get("reset_device", 0) >= 1  # the USB reset unblocked the stuck call
    assert await svc.call(lambda b: b.model()) == "Nikon DSC D500"
    assert len(await svc.capture(timeout=5)) == 1


async def test_connect_after_timeout_uses_a_fresh_worker(make: Make) -> None:
    fake = FakeCamera()
    svc = await make(fake, stuck_grace_s=60, zombie_wait_s=2.0)
    fake.hang("capture")
    with pytest.raises(CameraTimeout):
        await svc.call(lambda b: b.capture(), timeout=0.1)
    assert svc.state == CameraState.ERROR
    st = await svc.connect()  # resets the USB device, abandons the stuck worker, reopens
    assert st.state == CameraState.IDLE
    assert await svc.call(lambda b: b.model()) == "Nikon DSC D500"


async def test_hung_open_does_not_wedge_later_connects(make: Make) -> None:
    fake = FakeCamera()
    svc = await make(fake, connect=False, zombie_wait_s=2.0)
    fake.hang("open")
    with pytest.raises(CameraTimeout):
        await svc.connect()  # open() hangs; connect_timeout_s is 1 s
    assert svc.state == CameraState.DISCONNECTED
    st = await svc.connect()  # reset unblocks the stuck open, then a fresh worker connects
    assert st.state == CameraState.IDLE


async def test_hang_disconnect_connect_resets_usb_before_reopening(make: Make) -> None:
    fake = FakeCamera()
    svc = await make(fake, stuck_grace_s=60, zombie_wait_s=2.0, disconnect_wait_s=0.1)
    fake.hang("capture")
    task = asyncio.create_task(svc.call(lambda b: b.capture(), timeout=30))
    await until(lambda: fake.calls.get("capture", 0) == 1)
    await svc.disconnect()
    with pytest.raises(Exception):  # noqa: B017 - the in-flight caller is failed
        await task
    assert fake.calls.get("reset_device", 0) == 0
    st = await svc.connect()
    assert st.state == CameraState.IDLE
    assert fake.calls.get("reset_device", 0) >= 1


async def test_stray_file_is_recorded_not_attributed_or_lost(make: Make) -> None:
    fake = FakeCamera()
    svc = await make(fake)
    fake.press_shutter()  # body shutter: FILE_ADDED queued outside any capture
    files = await svc.capture(timeout=5)
    assert len(files) == 1 and len(svc.stray_files) == 1
