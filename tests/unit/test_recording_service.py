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
    CameraTimeout,
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


async def test_internal_ram_capture_target_is_only_a_warning(rig: Rig) -> None:
    await rig.cam.set_setting("capturetarget", "Internal RAM")
    info = await rig.rec.start(max_seconds=None, download_after=False)
    assert info.active and info.warning and "Internal RAM" in info.warning
    await rig.rec.stop()


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


async def test_movie_readback_off_does_not_end_a_healthy_recording(rig: Rig) -> None:
    """The movie getter is an action toggle; its readback must never end a recording."""
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake._values["movie"] = False  # readback off, no event
    rig.clock.thaw()
    await until(lambda: rig.clock.t >= 30)  # well past the old 2-poll detection
    assert rig.rec.info().active and rig.cam.state == S.RECORDING
    await rig.rec.stop()


async def test_segment_event_mid_recording_does_not_stop_it(rig: Rig) -> None:
    """A 4 GB split yields a FILE_ADDED while the camera keeps recording."""
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.fake.set_config("movie", False)  # emits a movie file event
    rig.fake.set_config("movie", True)
    rig.clock.thaw()
    await until(lambda: rig.rec.info().segments == 1)
    await until(lambda: rig.clock.t >= 30)  # far past any quiet window
    info = rig.rec.info()
    assert info.active and rig.cam.state == S.RECORDING and info.note is None
    await rig.rec.stop()


async def test_note_after_camera_clip_limit_and_stop_still_runs(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    rig.clock.t = 1799 - 2
    rig.clock.thaw()
    await until(lambda: not rig.rec.info().active)
    info = rig.rec.info()
    assert info.reason == "max_seconds" and info.note and "probably stopped" in info.note
    assert not rig.fake.get_config("movie").value


async def _reset_camera(rig: Rig) -> None:
    """Escalating timeout (as a slow live view preview would cause): RECORDING -> ERROR -> IDLE."""
    rig.fake.hang("get_config")
    with pytest.raises(CameraTimeout):
        await rig.cam.call(lambda b: b.get_config("iso"), owner="recording", timeout=0.05)
    assert rig.cam.state == S.ERROR
    rig.fake.release_all()
    await until(lambda: rig.cam.state == S.IDLE)


async def test_camera_reset_mid_recording_still_sends_movie_stop(rig: Rig) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    await _reset_camera(rig)
    assert rig.fake.get_config("movie").value  # camera is still recording
    rig.clock.thaw()
    await until(lambda: not rig.rec.info().active)
    info = rig.rec.info()
    assert info.reason == "camera_reset" and info.last_clip is not None
    assert not rig.fake.get_config("movie").value
    assert rig.cam.status().leased_by is None


async def test_camera_reset_with_failing_stop_keeps_recording_active_and_stop_retries(
    rig: Rig,
) -> None:
    await rig.rec.start(max_seconds=None, download_after=False)
    await _reset_camera(rig)
    rig.fake.fail_next("set_config", 3, exc=CameraOperationFailed("x"))
    rig.clock.thaw()
    await until(lambda: rig.rec.info().warning is not None)
    info = rig.rec.info()
    assert info.active and info.reason == "camera_reset" and "Retry" in (info.warning or "")
    assert rig.cam.status().leased_by == "recording"
    done = await rig.rec.stop()
    assert not done.active and done.last_clip is not None
    assert not rig.fake.get_config("movie").value


async def test_cancelled_start_after_movie_command_sends_movie_stop(rig: Rig) -> None:
    rig.fake.hang("set_config")
    task = asyncio.create_task(rig.rec.start(max_seconds=None, download_after=False))
    await until(lambda: rig.fake.calls.get("set_config", 0) >= 1)
    task.cancel()
    await asyncio.sleep(0.01)
    rig.fake.release_all()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not rig.fake.get_config("movie").value  # undone, not left recording untracked
    assert rig.fake.calls["set_config"] >= 2
    assert rig.cam.status().leased_by is None and not rig.rec.info().active


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
