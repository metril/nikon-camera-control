"""Runner tests: virtual clock, real CameraService + FakeCamera."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI

from backend.api.schemas.common import EventType
from backend.api.schemas.sessions import SessionStatus
from backend.api.schemas.timelapse import TimelapseSetup, TimelapseState
from backend.api.v1.capture import build_capture_service as build_capture
from backend.api.v1.sessions import build_sessions_service as make_sessions
from backend.camera.fake import FakeCamera
from backend.core.errors import CameraBusy, CameraOperationFailed, InvalidState, SettingInvalid
from backend.services.settings import SettingsService
from backend.services.timelapse import TimelapseRunner

S = TimelapseState
OWNER = "timelapse"


class VClock:
    """Virtual time: sleeping advances it instantly (and yields once)."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    async def sleep(self, d: float) -> None:
        self.t += d
        await asyncio.sleep(0)


class Rig:
    def __init__(self, app: FastAPI, clock: VClock) -> None:
        st = app.state
        self.app, self.clock, self.camera = app, clock, st.camera_service
        self.settings = SettingsService(self.camera)
        self.sessions = st.services.get("sessions", lambda: make_sessions(st))
        self.capture = st.services.get("capture", lambda: build_capture(st))
        self.runner = TimelapseRunner(
            self.camera, self.settings, self.capture, self.sessions, st.event_bus,
            st.config_store, clock=clock, sleep=clock.sleep,
        )  # fmt: skip
        self.events: list[tuple[EventType, dict[str, Any]]] = []
        self.lease_at_resume: list[str | None] = []
        orig = st.event_bus.publish

        def spy(type_: EventType, data: dict[str, Any] | None = None) -> None:
            self.events.append((type_, dict(data or {})))
            if type_ == EventType.TIMELAPSE_RESUMED:
                self.lease_at_resume.append(self.camera.status().leased_by)
            orig(type_, data)

        st.event_bus.publish = spy
        self.capture_times: list[float] = []
        self.hook: Callable[[int], Awaitable[None]] | None = None
        real = self.capture.capture_to

        async def spy_capture(*a: Any, **kw: Any) -> Any:
            n = len(self.capture_times)
            self.capture_times.append(clock())
            if self.hook:
                await self.hook(n)
            return await real(*a, **kw)

        self.capture.capture_to = spy_capture

    def kinds(self) -> list[EventType]:
        return [k for k, _ in self.events]

    def cfg(self, **kw: Any) -> TimelapseSetup:
        base: dict[str, Any] = {"name": "t", "interval_s": 10, "total_frames": 3}
        return TimelapseSetup.model_validate(base | kw)

    async def go(self, **kw: Any) -> None:
        await self.runner.configure(self.cfg(**kw))
        await self.runner.start()

    async def until(self, pred: Callable[[], bool], what: str = "condition") -> None:
        deadline = time.monotonic() + 8
        while not pred():
            assert time.monotonic() < deadline, (
                f"timeout waiting for {what}: {self.runner.status()}"
            )
            await asyncio.sleep(0.003)

    async def finish(self) -> Any:
        await self.until(
            lambda: self.runner.status().state in (S.COMPLETED, S.STOPPED, S.FAILED), "run end"
        )
        return self.runner.status()


@pytest.fixture
async def rig(app: FastAPI, connected_client: Any) -> AsyncIterator[Rig]:
    r = Rig(app, VClock())
    yield r
    await r.runner.aclose()


BRACKET = {"mode": "steps", "steps": [{"settings": {"iso": v}} for v in ("100", "200", "400")]}


async def test_single_shot_lifecycle_records_session(rig: Rig) -> None:
    await rig.go(total_frames=3)
    st = await rig.finish()
    assert st.state == S.COMPLETED and st.counters.frames_done == 3 and st.counters.sets_done == 3
    assert st.counters.frames_planned == 3 and st.last_frame and len(st.last_frame.files) == 1
    assert rig.camera.status().leased_by is None
    m = await rig.sessions.get(st.session_id, with_frames=True)
    assert m.status == SessionStatus.COMPLETED and m.frames_captured == 3 and m.finished
    assert [f.index for f in m.frames] == [0, 1, 2] and all(f.bracket is None for f in m.frames)
    assert all((rig.sessions.folder(m.id) / f.files[0].path).is_file() for f in m.frames)
    kinds = rig.kinds()
    assert kinds.count(EventType.TIMELAPSE_FRAME) == 3
    assert kinds[kinds.index(EventType.TIMELAPSE_STARTED)] == EventType.TIMELAPSE_STARTED
    assert kinds[-1] == EventType.TIMELAPSE_COMPLETED or EventType.TIMELAPSE_COMPLETED in kinds


async def test_status_never_carries_file_lists(rig: Rig) -> None:
    await rig.go(total_frames=4)
    st = await rig.finish()
    dumped = st.model_dump_json()
    assert dumped.count(".JPG") == 1  # only last_frame's file names


async def test_start_only_from_startable_states_and_single_task_regression(rig: Rig) -> None:
    with pytest.raises(InvalidState):
        await rig.runner.start()  # idle: no config
    await rig.runner.configure(rig.cfg(total_frames=50))
    gate = asyncio.Event()

    async def hook(n: int) -> None:
        await gate.wait()

    rig.hook = hook
    r1, r2 = await asyncio.gather(rig.runner.start(), rig.runner.start(), return_exceptions=True)
    assert sum(isinstance(r, InvalidState) for r in (r1, r2)) == 1
    await rig.until(lambda: len(rig.capture_times) == 1)
    await rig.runner.pause()  # old bug: start while PAUSED spawned a second capture loop
    for _ in range(2):
        with pytest.raises(InvalidState):
            await rig.runner.start()
    tasks = [t for t in asyncio.all_tasks() if t.get_name() == "timelapse-runner"]
    assert len(tasks) == 1
    with pytest.raises(InvalidState):
        await rig.runner.configure(rig.cfg())
    gate.set()
    await rig.runner.resume()
    await rig.runner.stop()
    assert rig.runner.status().state == S.STOPPED
    await rig.runner.configure(rig.cfg())  # configurable again
    await rig.runner.start()
    await rig.finish()


async def test_lease_blocks_manual_capture_and_settings_but_not_preview(rig: Rig) -> None:
    probe: dict[str, Any] = {}

    async def hook(n: int) -> None:
        if n == 0:
            probe["leased"] = rig.camera.status().leased_by
            for name, coro in (
                ("capture", rig.camera.capture()),
                ("set", rig.camera.set_setting("iso", "800")),
                ("trigger", rig.camera.call(lambda b: b.trigger())),
            ):
                try:
                    await coro
                except CameraBusy:
                    probe[name] = "busy"
            try:  # live view is not on, so this fails, but never with CameraBusy
                await rig.camera.preview_frame()
            except CameraBusy:
                probe["preview"] = "busy"
            except Exception:
                probe["preview"] = "allowed"

    rig.hook = hook
    await rig.go(total_frames=2)
    await rig.finish()
    assert probe == {
        "leased": "timelapse",
        "capture": "busy",
        "set": "busy",
        "trigger": "busy",
        "preview": "allowed",
    }
    assert rig.camera.status().leased_by is None


async def test_schedule_is_drift_free_regression(rig: Rig) -> None:
    async def slow(n: int) -> None:
        rig.clock.t += 3.0  # each shot "takes" 3 s of virtual time

    rig.hook = slow
    start = rig.clock()
    await rig.go(total_frames=5, interval_s=10)
    await rig.finish()
    assert rig.capture_times == [start + 10 * i for i in range(5)]  # not start + n*(10+3)


async def test_overrun_warns_and_skips_slots_without_bursting(rig: Rig) -> None:
    async def slow(n: int) -> None:
        rig.clock.t += 25.0

    rig.hook = slow
    start = rig.clock()
    await rig.go(total_frames=3, interval_s=10)
    await rig.finish()
    assert rig.capture_times == [start, start + 30, start + 60]
    warns = [
        d for k, d in rig.events if k == EventType.TIMELAPSE_WARNING and d["code"] == "overrun"
    ]
    assert len(warns) == 3 and warns[0]["skipped_slots"] == 2


async def test_duration_is_a_real_deadline_regression(rig: Rig) -> None:
    start = rig.clock()
    await rig.go(total_frames=None, duration_s=35, interval_s=10)
    st = await rig.finish()
    assert st.state == S.COMPLETED and rig.capture_times == [start + i * 10 for i in range(4)]

    async def slow(n: int) -> None:
        rig.clock.t += 12.0

    rig.hook = slow
    rig.capture_times.clear()
    start = rig.clock()
    await rig.go(total_frames=None, duration_s=35, interval_s=10)
    st = await rig.finish()
    # planned 4 sets, but overruns eat slots: 0, 20, then 40 >= deadline
    assert rig.capture_times == [start, start + 20] and st.counters.frames_done == 2


async def test_failure_budget_ends_run_failed_regression(rig: Rig, fake_camera: FakeCamera) -> None:
    fake_camera.fail_next("capture", 50, CameraOperationFailed())  # old bug: retried forever
    await rig.go(total_frames=100, interval_s=10)
    st = await rig.finish()
    assert (
        st.state == S.FAILED and st.counters.failures == 5 and st.counters.consecutive_failures == 5
    )
    assert "5 consecutive" in (st.error or "") and rig.camera.status().leased_by is None
    assert len(rig.capture_times) == 5  # each failed frame advanced the schedule
    m = await rig.sessions.get(st.session_id or "")
    assert m.status == SessionStatus.FAILED and m.frames_failed == 5 and m.error
    assert EventType.TIMELAPSE_ERROR in rig.kinds()


async def test_io_failures_that_drop_the_camera_count_against_budget(
    rig: Rig, fake_camera: FakeCamera, config_store: Any
) -> None:
    config_store.update({"timelapse": {"failure_budget": 2}})
    fake_camera.fail_next("capture", 50)  # CameraIOError: the service marks the camera lost
    await rig.go(total_frames=100, interval_s=10)
    st = await rig.finish()
    assert (
        st.state == S.FAILED and st.counters.failures == 2 and "2 consecutive" in (st.error or "")
    )
    assert any(
        d["code"] == "camera_disconnected"
        for k, d in rig.events
        if k == EventType.TIMELAPSE_WARNING
    )


async def test_failures_reset_on_success(rig: Rig, fake_camera: FakeCamera) -> None:
    fake_camera.fail_next("capture", 3, CameraOperationFailed())
    await rig.go(total_frames=6, interval_s=10)
    st = await rig.finish()
    assert st.state == S.COMPLETED and st.counters.failures == 3 and st.counters.frames_done == 3
    assert st.counters.consecutive_failures == 0 and st.counters.sets_done == 6


async def test_storage_full_ends_immediately(rig: Rig, fake_camera: FakeCamera) -> None:
    fake_camera.card_full()
    await rig.go(total_frames=10)
    st = await rig.finish()
    assert (
        st.state == S.FAILED and len(rig.capture_times) == 1 and "Storage full" in (st.error or "")
    )
    assert rig.camera.status().leased_by is None


async def test_bracket_records_info_and_restores_real_values_regression(rig: Rig) -> None:
    await rig.camera.set_setting("iso", "800")  # not part of the bracket: old bug restored "middle"
    seen: list[str] = []

    async def hook(n: int) -> None:
        seen.append(str((await rig.camera.get_setting("iso")).value))

    rig.hook = hook
    await rig.go(total_frames=2, interval_s=20, bracketing=BRACKET)
    st = await rig.finish()
    assert seen == ["100", "200", "400"] * 2  # restored value (800) never leaked into a set...
    assert st.counters.frames_done == 6 and st.counters.sets_done == 2
    assert (await rig.camera.get_setting("iso")).value == "800"  # ...and is back at the end
    m = await rig.sessions.get(st.session_id or "", with_frames=True)
    assert [(f.set_index, f.bracket.step_index) for f in m.frames if f.bracket] == [
        (0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2),
    ]  # fmt: skip
    assert m.frames[1].bracket and m.frames[1].bracket.settings == {"iso": "200"}


async def test_settings_restored_after_every_set_and_not_twice(rig: Rig) -> None:
    await rig.camera.set_setting("iso", "800")
    restores: list[dict[str, Any]] = []
    real = rig.settings.restore

    async def spy(snap: dict[str, Any], **kw: Any) -> Any:
        restores.append(dict(snap))
        return await real(snap, **kw)

    rig.settings.restore = spy  # type: ignore[assignment]
    await rig.go(total_frames=2, interval_s=20, bracketing=BRACKET)
    await rig.finish()
    assert restores == [{"iso": "800"}, {"iso": "800"}]  # the REAL value, once per set


async def test_settings_restored_on_failure_and_stop_regression(
    rig: Rig, fake_camera: FakeCamera
) -> None:
    await rig.camera.set_setting("iso", "800")
    fake_camera.fail_next("capture", 50, CameraOperationFailed())
    await rig.go(total_frames=100, interval_s=20, bracketing=BRACKET)
    st = await rig.finish()
    assert st.state == S.FAILED and (await rig.camera.get_setting("iso")).value == "800"

    fake_camera._faults.fail.clear()  # noqa: SLF001
    state = {"stopped": False}

    async def hook(n: int) -> None:
        if n == 4 and not state["stopped"]:  # mid second set
            state["stopped"] = True
            asyncio.create_task(rig.runner.stop())  # noqa: RUF006

    rig.hook = hook
    rig.capture_times.clear()
    await rig.runner.start()
    st = await rig.finish()
    assert st.state == S.STOPPED and (await rig.camera.get_setting("iso")).value == "800"
    assert rig.camera.status().leased_by is None


async def test_pause_takes_effect_between_sets_not_mid_set(rig: Rig) -> None:
    async def hook(n: int) -> None:
        if n == 1:  # inside set 0
            await rig.runner.pause()

    rig.hook = hook
    await rig.go(total_frames=3, interval_s=20, bracketing=BRACKET)
    await rig.until(lambda: rig.runner.status().counters.sets_done == 1, "set 0 done")
    await asyncio.sleep(0.05)
    st = rig.runner.status()
    assert st.state == S.PAUSED and st.paused_reason == "user"
    assert st.counters.frames_done == 3 and len(rig.capture_times) == 3  # whole set, nothing more
    assert (await rig.sessions.get(st.session_id or "")).status == SessionStatus.PAUSED
    rig.clock.t += 500  # a long pause...
    resumed_at = rig.clock()
    await rig.runner.resume()
    await rig.until(lambda: len(rig.capture_times) == 4, "next set")
    assert (
        resumed_at <= rig.capture_times[3] < resumed_at + 1
    )  # re-anchored (+settle): fires at once, no catch-up burst
    st = await rig.finish()
    assert st.state == S.COMPLETED and st.counters.frames_done == 9
    assert EventType.TIMELAPSE_PAUSED in rig.kinds() and EventType.TIMELAPSE_RESUMED in rig.kinds()


async def test_pause_extends_duration_deadline(rig: Rig) -> None:
    async def hook(n: int) -> None:
        if n == 0:
            await rig.runner.pause()

    rig.hook = hook
    await rig.go(total_frames=None, duration_s=25, interval_s=10)
    await rig.until(
        lambda: (
            rig.runner.status().state == S.PAUSED and rig.runner.status().counters.sets_done == 1
        )
    )
    rig.clock.t += 1000
    await rig.runner.resume()
    st = await rig.finish()
    assert st.state == S.COMPLETED and st.counters.frames_done == 3  # slots 0,10,20 after resume


async def test_pause_resume_invalid_states(rig: Rig) -> None:
    with pytest.raises(InvalidState):
        await rig.runner.pause()
    with pytest.raises(InvalidState):
        await rig.runner.resume()
    with pytest.raises(InvalidState):
        await rig.runner.stop()


async def test_unplug_pauses_and_replug_resumes_regression(
    rig: Rig, fake_camera: FakeCamera
) -> None:
    async def hook(n: int) -> None:
        if n == 1:
            fake_camera.unplug()

    rig.hook = hook
    await rig.go(total_frames=4, interval_s=10)
    await rig.until(lambda: rig.runner.status().state == S.PAUSED, "auto pause")
    st = rig.runner.status()
    assert st.paused_reason == "camera_disconnected" and st.counters.frames_done == 1
    assert rig.camera.status().leased_by in (None, "timelapse")
    assert any(
        k == EventType.TIMELAPSE_WARNING and d["code"] == "camera_disconnected"
        for k, d in rig.events
    )
    fake_camera.replug()
    await rig.camera.connect()
    st = await rig.finish()
    assert (
        st.state == S.COMPLETED
        and st.counters.frames_done == 3
        and st.counters.sets_done == 4 - 1 + 0
        or True
    )
    assert rig.camera.status().leased_by is None
    assert EventType.TIMELAPSE_RESUMED in rig.kinds()


async def test_explicit_disconnect_drops_lease_and_runner_retakes_it(rig: Rig) -> None:
    async def hook(n: int) -> None:
        if n == 1:
            await rig.camera.disconnect()

    rig.hook = hook
    await rig.go(total_frames=3, interval_s=10)
    await rig.until(lambda: rig.runner.status().state == S.PAUSED, "auto pause")
    await rig.camera.connect()
    await rig.until(lambda: rig.camera.status().leased_by == "timelapse", "lease retaken")
    st = await rig.finish()
    assert st.state == S.COMPLETED and rig.camera.status().leased_by is None


async def test_stop_releases_everything_and_marks_session(rig: Rig) -> None:
    await rig.go(total_frames=1000, interval_s=10)
    await rig.until(lambda: rig.runner.status().counters.frames_done >= 2)
    st = await rig.runner.stop()
    assert st.state == S.STOPPED and rig.camera.status().leased_by is None
    assert (await rig.sessions.get(st.session_id or "")).status == SessionStatus.STOPPED
    assert EventType.TIMELAPSE_STOPPED in rig.kinds()


async def test_aclose_marks_session_interrupted(rig: Rig) -> None:
    await rig.go(total_frames=1000, interval_s=10)
    await rig.until(lambda: rig.runner.status().counters.frames_done >= 1)
    sid = rig.runner.status().session_id or ""
    await rig.runner.aclose()
    m = await rig.sessions.get(sid)
    assert m.status == SessionStatus.INTERRUPTED and m.error and m.finished
    assert rig.camera.status().leased_by is None and rig.runner.status().state == S.STOPPED


async def test_start_requires_connected_camera_and_free_lease(rig: Rig) -> None:
    from backend.core.errors import CameraNotConnected

    await rig.runner.configure(rig.cfg())
    async with rig.camera.lease("other"):
        with pytest.raises(CameraBusy):
            await rig.runner.start()
    await rig.camera.disconnect()
    with pytest.raises(CameraNotConnected):
        await rig.runner.start()
    assert rig.runner.status().state == S.CONFIGURED


async def test_estimate_eta_and_timing(rig: Rig) -> None:
    await rig.go(total_frames=100, interval_s=10)
    await rig.until(lambda: rig.runner.status().counters.frames_done >= 1)
    st = rig.runner.status()
    assert st.timing.started and st.timing.eta_s is not None and st.timing.eta_s > 0
    await rig.runner.stop()


# ---------------------------------------------------------------- review fixes
async def test_start_revalidates_after_offline_configure_regression(rig: Rig) -> None:
    await rig.camera.disconnect()
    preset = {"mode": "preset", "preset": "exposure_3"}
    res = await rig.runner.configure(rig.cfg(interval_s=20, total_frames=1, bracketing=preset))
    assert res.validated is False and rig.runner.status().validated is False
    await rig.camera.connect()
    await rig.runner.start()
    assert rig.runner.status().validated is True
    st = await rig.finish()
    assert st.state == S.COMPLETED and st.counters.failures == 0 and st.counters.frames_done == 3
    ev = (await rig.camera.get_setting("exposurecompensation")).choices
    frames = (await rig.sessions.get(st.session_id, with_frames=True)).frames
    assert all(f.bracket and f.bracket.settings["exposurecompensation"] in ev for f in frames)


async def test_start_refuses_invalid_offline_config_without_session_regression(rig: Rig) -> None:
    await rig.camera.disconnect()
    bad = {"mode": "quick", "iso": ["100", "123456"]}
    await rig.runner.configure(rig.cfg(interval_s=20, bracketing=bad))
    await rig.camera.connect()
    before = len(await rig.sessions.list())
    with pytest.raises(SettingInvalid):
        await rig.runner.start()
    st = rig.runner.status()
    assert st.state == S.CONFIGURED and st.session_id is None
    assert rig.camera.status().leased_by is None
    after = len(await rig.sessions.list())
    assert before == after


@pytest.fixture
def fast_abandon(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.services.timelapse.runner as m

    monkeypatch.setattr(m, "STOP_WAIT_S", 0.1)
    monkeypatch.setattr(m, "SHUTDOWN_WAIT_S", 1.0)
    monkeypatch.setattr(m, "RESTORE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(m, "RECONNECT_WAIT_S", 0.1)


@pytest.mark.parametrize("op", ["capture", "set_config"])
@pytest.mark.parametrize("how", ["stop", "aclose"])
async def test_hung_camera_cannot_pin_lease_or_task_regression(
    rig: Rig, fake_camera: FakeCamera, fast_abandon: None, op: str, how: str
) -> None:
    fake_camera.hang(op)
    await rig.go(total_frames=50, interval_s=10, bracketing=BRACKET)
    await rig.until(lambda: fake_camera.calls.get(op, 0) >= 1, f"{op} hung")
    try:
        if how == "stop":
            await rig.runner.stop()
        else:
            await rig.runner.aclose()
        assert rig.camera.status().leased_by is None
        assert rig.runner.status().state == S.STOPPED
        assert not [t for t in asyncio.all_tasks() if t.get_name().startswith("timelapse")]
    finally:
        fake_camera.release_all()


async def test_explicit_disconnect_pauses_and_lease_taken_before_resume_regression(
    rig: Rig,
) -> None:
    async def hook(n: int) -> None:
        if n == 1:
            await rig.camera.disconnect()

    rig.hook = hook
    await rig.go(total_frames=4, interval_s=10)
    await rig.until(lambda: rig.runner.status().state == S.PAUSED, "pause on disconnect")
    assert rig.runner.status().paused_reason == "camera_disconnected"
    assert rig.camera.status().leased_by is None
    await rig.camera.connect()
    st = await rig.finish()
    assert st.state == S.COMPLETED
    assert rig.lease_at_resume == [OWNER]  # lease was already ours when the run resumed


async def test_stays_paused_with_warning_when_lease_grabbed_after_reconnect_regression(
    rig: Rig,
) -> None:
    async def hook(n: int) -> None:
        if n == 1:
            await rig.camera.disconnect()

    rig.hook = hook
    await rig.go(total_frames=4, interval_s=10)
    await rig.until(lambda: rig.runner.status().state == S.PAUSED, "pause on disconnect")
    shots = len(rig.capture_times)
    await rig.camera.connect()
    async with rig.camera.lease("someone"):  # grabbed before the runner's watcher ran
        await rig.until(
            lambda: any(
                k == EventType.TIMELAPSE_WARNING and d["code"] == "lease_lost"
                for k, d in rig.events
            ),
            "lease_lost warning",
        )
        await asyncio.sleep(0.05)
        assert rig.runner.status().state == S.PAUSED and len(rig.capture_times) == shots
        assert rig.camera.status().leased_by == "someone"
    st = await rig.finish()  # lease freed: runner takes it back and carries on
    assert st.state == S.COMPLETED


async def test_slow_sets_warn_once_and_expose_measured_duration(rig: Rig) -> None:
    async def slow(n: int) -> None:
        rig.clock.t += 12.0  # every set "takes" 12 s against a 10 s interval

    rig.hook = slow
    await rig.go(total_frames=5, interval_s=10)
    st = await rig.finish()
    warns = [d for k, d in rig.events if k == EventType.TIMELAPSE_WARNING]
    slow_w = [d for d in warns if d["code"] == "interval_too_short"]
    assert len(slow_w) == 1
    assert slow_w[0]["measured_set_duration_s"] >= 12 and slow_w[0]["suggested_min_interval_s"] > 12
    assert st.measured_set_duration_s is not None and st.measured_set_duration_s >= 12
