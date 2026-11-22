"""RecordingService against a real CameraService over FakeCamera, on virtual time."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from backend.api.schemas.common import EventType
from backend.camera.fake import FakeCamera
from backend.core.camera_service import CameraService
from backend.core.config_store import AppConfig, ConfigStore
from backend.core.errors import (
    CameraBusy,
    CameraNotConnected,
    CameraOperationFailed,
    InvalidState,
)
from backend.core.events import EventBus
from backend.core.jobs import JobManager, JobStatus
from backend.core.state import CameraState as S
from backend.services.liveview import LiveViewService
from backend.services.recording import RecordingService


async def until(pred: Callable[[], bool], limit: float = 3.0) -> None:
    deadline = time.monotonic() + limit
    while not pred():
        assert time.monotonic() < deadline, "condition not reached"
        await asyncio.sleep(0.005)


class VClock:
    """Virtual time: each watchdog sleep advances the clock; ``frozen`` parks it forever."""

    def __init__(self) -> None:
        self.t = 0.0
        self.frozen = True
        self.gate = asyncio.Event()

    def thaw(self) -> None:
        self.frozen = False
        self.gate.set()

    def now(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        if self.frozen:
            await self.gate.wait()
        self.t += s
        await asyncio.sleep(0.002)


class Rig:
    def __init__(self, tmp: Path, fake: FakeCamera) -> None:
        self.fake = fake
        self.clock = VClock()
        cfg = AppConfig.model_validate({"camera": {"keepalive_interval_s": 5.0}})
        self.store = ConfigStore(tmp / "c.json", initial=cfg)
        self.bus = EventBus()
        self.cam = CameraService(lambda: fake, self.store, self.bus, event_quiet_window_s=0.01)
        self.jobs = JobManager(self.bus)
        self.out = tmp / "out"
        self.lv = LiveViewService(self.cam, self.bus, self.store, interval_s=0.005)
        self.rec = RecordingService(
            self.cam,
            self.bus,
            self.jobs,
            self.out,
            liveview_running=lambda: self.lv.running,
            clock=self.clock.now,
            sleep=self.clock.sleep,
            retry_delay_s=0.0,
        )


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Rig]:
    r = Rig(tmp_path, FakeCamera())
    await r.cam.start()
    await r.cam.connect()
    yield r
    await r.rec.aclose()
    await r.lv.aclose()
    await r.jobs.shutdown()
    await r.cam.stop()


async def test_start_stop_from_idle_restores_idle_and_viewfinder_off(rig: Rig) -> None:
    info = await rig.rec.start(max_seconds=None, download_after=False)
    assert info.active and info.max_seconds == 1799
    assert rig.cam.state == S.RECORDING and rig.fake.viewfinder_on
    assert rig.cam.status().leased_by == "recording"
    done = await rig.rec.stop()
    assert not done.active and done.reason == "user" and done.warning is None
    clip, size = done.last_clip  # type: ignore[misc]
    assert clip.name.endswith(".MOV") and size > 0
    assert any(f.name == clip.name for f in rig.fake.list_files(clip.folder))
    assert rig.cam.state == S.IDLE and not rig.fake.viewfinder_on
    assert rig.cam.status().leased_by is None


async def test_start_stop_from_liveview_returns_to_liveview(rig: Rig) -> None:
    await rig.lv.start()
    await until(lambda: rig.cam.state == S.LIVEVIEW)
    await rig.rec.start(max_seconds=30, download_after=False)
    assert rig.cam.state == S.RECORDING
    await rig.rec.stop()
    assert rig.cam.state == S.LIVEVIEW and rig.fake.viewfinder_on
    assert rig.cam.status().leased_by is None


async def test_liveview_subscriber_keeps_getting_frames_while_recording(rig: Rig) -> None:
    sub = rig.lv.subscribe()
    await until(lambda: rig.cam.state == S.LIVEVIEW)
    await rig.rec.start(max_seconds=None, download_after=False)
    n0 = rig.lv.stats().frames_produced
    await until(lambda: rig.lv.stats().frames_produced >= n0 + 3)
    assert rig.lv.stats().active and rig.cam.state == S.RECORDING
    await rig.rec.stop()
    assert rig.cam.state == S.LIVEVIEW  # subscriber still wants the stream
    rig.lv.unsubscribe(sub)


async def test_recording_started_during_stream_does_not_drop_liveview_on_stop(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    sub = rig.lv.subscribe()  # subscriber arrives mid-recording
    await until(lambda: rig.lv.stats().active)
    await rig.rec.stop()
    assert rig.cam.state == S.LIVEVIEW
    rig.lv.unsubscribe(sub)
    await until(lambda: rig.cam.state == S.IDLE)


async def test_auto_stop_at_max_seconds_on_virtual_time(rig: Rig) -> None:
    await rig.rec.start(max_seconds=5, download_after=False)
    rig.clock.thaw()  # one-second virtual polls
    await until(lambda: not rig.rec.info().active)
    info = rig.rec.info()
    assert info.reason == "max_seconds" and info.elapsed_s >= 5 and info.last_clip is not None
    assert rig.cam.state == S.IDLE and rig.cam.status().leased_by is None


async def test_others_blocked_while_recording(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    with pytest.raises(CameraBusy):
        await rig.cam.capture()
    with pytest.raises(CameraBusy):
        await rig.cam.set_setting("iso", "200")
    await rig.rec.stop()


async def test_start_twice_and_stop_without_start_are_invalid_state(rig: Rig) -> None:
    with pytest.raises(InvalidState):
        await rig.rec.stop()
    await rig.rec.start(max_seconds=None, download_after=False)
    with pytest.raises(InvalidState):
        await rig.rec.start(max_seconds=None, download_after=False)
    await rig.rec.stop()


async def test_start_refused_when_capture_target_is_internal_ram(rig: Rig) -> None:
    await rig.cam.set_setting("capturetarget", "Internal RAM")
    with pytest.raises(InvalidState, match="memory card"):
        await rig.rec.start(max_seconds=None, download_after=False)
    assert rig.cam.state == S.IDLE and rig.cam.status().leased_by is None


async def test_start_failure_surfaces_movie_mode_hint_and_rolls_back(rig: Rig) -> None:
    rig.fake.fail_next("set_config", exc=CameraOperationFailed("refused"))
    with pytest.raises(CameraOperationFailed, match="movie mode"):
        await rig.rec.start(max_seconds=None, download_after=False)
    assert rig.cam.state == S.IDLE and not rig.fake.viewfinder_on
    assert rig.cam.status().leased_by is None and not rig.rec.info().active


async def test_start_when_disconnected_is_not_connected(rig: Rig) -> None:
    await rig.cam.disconnect()
    with pytest.raises(CameraNotConnected):
        await rig.rec.start(max_seconds=None, download_after=False)
    assert rig.cam.status().leased_by is None


async def test_stop_failure_is_retried(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake.fail_next(
        "set_config", 2, exc=CameraOperationFailed("x")
    )  # attempts 1 and 2 fail, 3 succeeds
    done = await rig.rec.stop()
    assert not done.active and done.last_clip is not None


async def test_stop_failure_after_all_retries_keeps_recording_and_can_retry(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake.fail_next("set_config", 3, exc=CameraOperationFailed("x"))
    with pytest.raises(CameraOperationFailed, match="FAILED TO STOP"):
        await rig.rec.stop()
    assert rig.rec.info().active and rig.cam.status().leased_by == "recording"
    done = await rig.rec.stop()
    assert not done.active and done.last_clip is not None


async def test_unplug_mid_recording_marks_ended_and_releases_lease(rig: Rig) -> None:
    sub = rig.bus.subscribe()
    seen: list[EventType] = []

    async def collect() -> None:
        async for e in sub:
            seen.append(e.type)

    task = asyncio.create_task(collect())
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake.unplug()
    rig.clock.thaw()
    await until(lambda: not rig.rec.info().active)
    info = rig.rec.info()
    assert info.reason == "camera_disconnected" and info.warning
    assert rig.cam.status().leased_by is None
    await until(lambda: EventType.RECORDING_STOPPED in seen)
    assert EventType.RECORDING_STARTED in seen
    sub.close()
    await task


async def test_camera_stopping_by_itself_is_noticed_and_clip_kept(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake.set_config("movie", False)  # e.g. card full / 29:59 limit on the body
    rig.clock.thaw()
    await until(lambda: not rig.rec.info().active)
    info = rig.rec.info()
    assert info.reason == "camera_stopped" and info.last_clip is not None
    assert rig.cam.state == S.IDLE and rig.cam.status().leased_by is None


async def test_download_after_submits_job_into_recordings_dir(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=True)
    done = await rig.rec.stop()
    assert done.job_id
    await until(lambda: rig.jobs.get(done.job_id).status == JobStatus.COMPLETED)  # type: ignore[arg-type]
    files = list((rig.out / "recordings").glob("*.MOV"))
    assert len(files) == 1 and files[0].stat().st_size > 0


async def test_shutdown_during_recording_stops_camera_and_releases(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    await rig.rec.aclose()
    assert not rig.rec.info().active and rig.rec.info().reason == "shutdown"
    assert rig.cam.state == S.IDLE and rig.cam.status().leased_by is None
    assert not rig.fake.get_config("movie").value
