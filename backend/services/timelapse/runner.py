"""Time-lapse runner: an explicit state machine driving one capture task.

State machine (``TimelapseState``)::

    idle -> configured -> running <-> paused
    running|paused -> stopping -> stopped
    running -> completed | failed
    completed|stopped|failed -> configured (new config) or running (start again)

Rules
-----
* ``start()`` is allowed only from configured/completed/stopped/failed and holds a lock, so
  there is never more than one runner task.
* The camera lease ``"timelapse"`` is held for the whole run (manual captures and settings
  writes get 409; live-view preview stays allowed). Every capture/settings call passes
  ``owner="timelapse"``.
* All mutable state is touched on the event loop only. ``clock``/``sleep`` are injectable.
* Scheduling is drift-free: set ``k`` is due at ``anchor + k * interval``. A set that overruns
  its slot publishes ``timelapse_warning`` and the schedule continues at the next free slot
  (no burst). ``duration_s`` is a real deadline: no set starts at or after it. Pause time is
  added to the deadline and a resume re-anchors the schedule (first set fires immediately).
* Pause takes effect between sets, never mid-set. ``pause()`` flips the state at once; the
  runner parks at the next set boundary. A camera disconnect pauses automatically
  (``paused_reason == "camera_disconnected"``) and resumes when the camera is back.
* Failure budget: each failed shot counts as a failed frame and the schedule moves on;
  ``timelapse.failure_budget`` consecutive failures end the run as ``failed``. ``StorageFull``
  (or ENOSPC) ends it at once. A shot that fails because the camera dropped counts too,
  then the run pauses until the camera is back.
* Bracketing: the camera's real values of every touched setting are snapshotted before the
  first set, restored after every set and again (in ``finally``) when the run ends.
* A camera disconnect (explicit or not) pauses the run at once (a bus watcher); an explicit
  disconnect also drops the lease. The runner re-takes the lease the moment the camera is back
  and BEFORE resuming; if someone else holds it by then it stays paused (``lease_lost``).
* ``start()`` re-validates the configuration against the connected camera (an offline
  ``configure`` is only provisional) and refuses to start, state unchanged, if it is invalid.
* Restores are bounded (``RESTORE_TIMEOUT_S``); ``stop()``/``aclose()`` wait a bounded time,
  cancel, and finally abandon a task stuck on a hung camera, always freeing the lease.
* ``aclose()`` stops a running session cleanly; its session is marked ``interrupted``.
  After a crash/restart there is no runner (status ``idle``) and the manifest is recovered as
  ``interrupted`` by ``SessionStore.recover_interrupted``.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import errno
import logging
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from backend.api.schemas.common import EventType
from backend.api.schemas.sessions import (
    BracketInfo,
    SessionFile,
    SessionFrame,
    SessionStatus,
)
from backend.api.schemas.timelapse import (
    BracketStep,
    Counters,
    LastFrame,
    TimelapseConfigResult,
    TimelapseSetup,
    TimelapseState,
    TimelapseStatus,
    Timing,
)
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraNotConnected,
    InvalidState,
    StorageFull,
)
from backend.core.events import EventBus, Subscription
from backend.services.capture import CaptureService
from backend.services.sessions import SessionStore
from backend.services.settings import SettingsService, SettingValue
from backend.services.storage import RAW_EXTS
from backend.services.timelapse.brackets import SETTLE_S
from backend.services.timelapse.config import ResolvedConfig, resolve_config, shot_bytes_for

log = logging.getLogger(__name__)

OWNER = "timelapse"
CAMERA_POLL_S = 1.0
STOP_WAIT_S = 120.0  # stop(): wait for a cooperative end, then cancel
SHUTDOWN_WAIT_S = 20.0  # after cancel: must exceed RESTORE_TIMEOUT_S + RECONNECT_WAIT_S
RESTORE_TIMEOUT_S = 15.0
RATE_SAMPLES = 5  # rolling window for the measured set duration
MIN_RATE_SAMPLES = 2
RECONNECT_WAIT_S = 3.0
_EPS = 1e-9

_STARTABLE = frozenset(
    {
        TimelapseState.CONFIGURED,
        TimelapseState.COMPLETED,
        TimelapseState.STOPPED,
        TimelapseState.FAILED,
    }
)
_ACTIVE = frozenset({TimelapseState.RUNNING, TimelapseState.PAUSED, TimelapseState.STOPPING})
_SESSION_STATUS = {
    TimelapseState.COMPLETED: SessionStatus.COMPLETED,
    TimelapseState.STOPPED: SessionStatus.STOPPED,
    TimelapseState.FAILED: SessionStatus.FAILED,
}

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[object]]


class _RunFailed(Exception):
    """Ends the run as ``failed`` with ``str(self)`` recorded."""


def _is_disk_full(e: BaseException) -> bool:
    return isinstance(e, StorageFull) or (isinstance(e, OSError) and e.errno == errno.ENOSPC)


class TimelapseRunner:
    def __init__(
        self,
        camera: CameraService,
        settings: SettingsService,
        capture: CaptureService,
        sessions: SessionStore,
        bus: EventBus,
        config_store: ConfigStore,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._camera = camera
        self._settings = settings
        self._capture = capture
        self._sessions = sessions
        self._bus = bus
        self._cfg = config_store
        self._clock = clock
        self._sleep = sleep

        self._state = TimelapseState.IDLE
        self._resolved: ResolvedConfig | None = None
        self._task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._wake = asyncio.Event()  # pause/resume/stop requests (outer loop)
        self._stop_wake = asyncio.Event()  # stop only (interrupts in-set waits)
        self._reset_run()

    def _reset_run(self) -> None:
        self._session_id: str | None = None
        self._frames_done = 0
        self._sets_done = 0
        self._failures = 0
        self._consecutive = 0
        self._set_seq = 0
        self._budget = 5
        self._stop_req = False
        self._shutdown = False
        self._user_pause = False
        self._cam_pause = False
        self._dirty = False
        self._restore_hung = False
        self._lease_warned = False
        self._slow_warned = False
        self._durations: collections.deque[float] = collections.deque(maxlen=RATE_SAMPLES)
        self._watcher: asyncio.Task[None] | None = None
        self._sub: Subscription | None = None
        self._snapshot: dict[str, SettingValue] = {}
        self._started_at: datetime | None = None
        self._started_mono: float | None = None
        self._finished_elapsed: float | None = None
        self._next_at: float | None = None
        self._deadline: float | None = None
        self._last_frame: LastFrame | None = None
        self._error: str | None = None
        self._wake.clear()
        self._stop_wake.clear()

    # ------------------------------------------------------------------ config / queries
    async def configure(self, cfg: TimelapseSetup) -> TimelapseConfigResult:
        if self._state in _ACTIVE or self._start_lock.locked():
            raise InvalidState(
                "Stop the time-lapse before changing its configuration",
                details={"state": str(self._state)},
            )
        connected = self._camera.status().connected
        shot_bytes = await self._shot_bytes() if connected else shot_bytes_for(None)
        resolved = await resolve_config(
            cfg,
            self._cfg.config.timelapse,
            settings=self._settings if connected else None,
            shot_bytes=shot_bytes,
        )
        if self._state in _ACTIVE or self._start_lock.locked():  # changed while validating
            raise InvalidState("Time-lapse started while validating the configuration")
        self._resolved = resolved
        self._reset_run()
        self._state = TimelapseState.CONFIGURED
        return resolved.result()

    async def _shot_bytes(self) -> int:
        try:
            v = (await self._settings.get("imagequality")).value
            return shot_bytes_for(str(v) if v is not None else None)
        except AppError:
            return shot_bytes_for(None)

    async def preview_draft(self, cfg: TimelapseSetup) -> TimelapseConfigResult:
        """Validate and estimate ``cfg`` with no side effects (usable while a run is active).

        While a run is active the camera is leased, so the draft is checked offline only
        (``validated`` false)."""
        busy = self._state in _ACTIVE or self._start_lock.locked()
        connected = self._camera.status().connected and not busy
        shot_bytes = await self._shot_bytes() if connected else shot_bytes_for(None)
        resolved = await resolve_config(
            cfg,
            self._cfg.config.timelapse,
            settings=self._settings if connected else None,
            shot_bytes=shot_bytes,
        )
        return resolved.result()

    def preview(self) -> TimelapseConfigResult:
        if self._resolved is None:
            raise InvalidState("No time-lapse configuration has been set")
        return self._resolved.result()

    def status(self) -> TimelapseStatus:
        r = self._resolved
        now = self._clock()
        active = self._state in _ACTIVE
        if self._finished_elapsed is not None and not active:
            elapsed = self._finished_elapsed
        elif self._started_mono is not None:
            elapsed = max(0.0, now - self._started_mono)
        else:
            elapsed = 0.0
        next_shot: datetime | None = None
        if self._next_at is not None and self._state == TimelapseState.RUNNING:
            next_shot = datetime.now(UTC) + timedelta(seconds=max(0.0, self._next_at - now))
        return TimelapseStatus(
            state=self._state,
            session_id=self._session_id,
            counters=Counters(
                frames_done=self._frames_done,
                frames_planned=r.planned_shots if r else 0,
                sets_done=self._sets_done,
                failures=self._failures,
                consecutive_failures=self._consecutive,
            ),
            timing=Timing(
                started=self._started_at,
                next_shot_at=next_shot,
                elapsed_s=round(elapsed, 3),
                eta_s=self._eta(now),
            ),
            config=r.config if r else None,
            last_frame=self._last_frame,
            paused_reason=self._pause_reason(),
            error=self._error,
            validated=bool(r and r.validated),
            measured_set_duration_s=self._measured(),
            failure_budget=self._budget_now(),
        )

    def _budget_now(self) -> int:
        if self._state in _ACTIVE or self._session_id is not None:
            return self._budget
        return self._cfg.config.timelapse.failure_budget

    def _measured(self) -> float | None:
        if not self._durations:
            return None
        return round(sum(self._durations) / len(self._durations), 3)

    def _pause_reason(self) -> Literal["user", "camera_disconnected"] | None:
        if self._state != TimelapseState.PAUSED:
            return None
        return "user" if self._user_pause else "camera_disconnected"

    def _eta(self, now: float) -> float | None:
        r = self._resolved
        if r is None or self._state not in (TimelapseState.RUNNING, TimelapseState.PAUSED):
            return None
        remaining = max(0, r.total_sets - self._sets_done)
        if remaining == 0:
            return 0.0
        iv = r.config.interval_s
        eta = (self._next_at - now if self._next_at is not None else 0.0) + (remaining - 1) * iv
        if self._deadline is not None:
            eta = min(eta, self._deadline - now)
        return round(max(0.0, eta), 3)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> TimelapseStatus:
        async with self._start_lock:
            if self._state not in _STARTABLE or (self._task is not None and not self._task.done()):
                raise InvalidState(
                    "Time-lapse can only be started when configured or finished",
                    details={"state": str(self._state)},
                )
            r = self._resolved
            if r is None:
                raise InvalidState("No time-lapse configuration has been set")
            if not self._camera.status().connected:
                raise CameraNotConnected()
            # An offline configure() is provisional: resolve again against the real camera.
            r = await resolve_config(
                r.config,
                self._cfg.config.timelapse,
                settings=self._settings,
                shot_bytes=await self._shot_bytes(),
            )
            self._resolved = r
            stack = AsyncExitStack()
            await stack.enter_async_context(self._camera.lease(OWNER))  # CameraBusy -> 409
            try:
                touched = sorted({k for s in r.steps for k in s.settings})
                snapshot = await self._settings.snapshot(touched) if touched else {}
                m = await self._sessions.create(
                    r.config.name, r.config.model_dump(mode="json"), r.planned_shots
                )
                await self._sessions.update(
                    m.id, status=SessionStatus.RUNNING, started=datetime.now(UTC)
                )
            except BaseException:
                await stack.aclose()
                raise
            self._reset_run()
            self._session_id = m.id
            self._snapshot = snapshot
            self._budget = self._cfg.config.timelapse.failure_budget
            self._started_at = datetime.now(UTC)
            self._started_mono = self._clock()
            self._stack = stack
            self._state = TimelapseState.RUNNING
            self._sub = self._bus.subscribe()
            self._watcher = asyncio.create_task(
                self._watch_camera(self._sub), name="timelapse-camera-watch"
            )
            self._task = asyncio.create_task(self._run(r), name="timelapse-runner")
            self._emit(EventType.TIMELAPSE_STARTED, planned_shots=r.planned_shots)
        return self.status()

    async def pause(self) -> TimelapseStatus:
        if self._state not in (TimelapseState.RUNNING, TimelapseState.PAUSED) or self._user_pause:
            raise InvalidState("Time-lapse is not running", details={"state": str(self._state)})
        self._user_pause = True
        await self._sync_pause_state()
        self._wake.set()
        return self.status()

    async def resume(self) -> TimelapseStatus:
        if self._state != TimelapseState.PAUSED or not self._user_pause:
            raise InvalidState("Time-lapse is not paused", details={"state": str(self._state)})
        self._user_pause = False
        await self._sync_pause_state()
        self._wake.set()
        return self.status()

    async def stop(self) -> TimelapseStatus:
        if self._state not in _ACTIVE:
            raise InvalidState("Time-lapse is not running", details={"state": str(self._state)})
        self._request_stop()
        task = self._task
        if task is not None:
            await asyncio.wait({task}, timeout=STOP_WAIT_S)
            if not task.done():
                await self._abandon(task)
        return self.status()

    async def _abandon(self, task: asyncio.Task[None]) -> None:
        """The task is stuck (hung camera): cancel it; if it still will not end, free the lease
        and settle the state ourselves so nothing is blocked on it."""
        task.cancel()
        await asyncio.wait({task}, timeout=SHUTDOWN_WAIT_S)
        if task.done():
            return
        log.error("time-lapse task did not end after cancel; abandoning it")
        await self._release_lease()
        await self._stop_watcher()
        self._state = TimelapseState.STOPPED
        self._next_at = None

    def _request_stop(self) -> None:
        self._stop_req = True
        if self._state in (TimelapseState.RUNNING, TimelapseState.PAUSED):
            self._state = TimelapseState.STOPPING
        self._wake.set()
        self._stop_wake.set()

    async def aclose(self) -> None:
        """Shutdown: stop cooperatively (session -> ``interrupted``), cancel if it hangs."""
        task = self._task
        if task is None or task.done():
            return
        self._shutdown = True
        self._request_stop()
        await asyncio.wait({task}, timeout=SHUTDOWN_WAIT_S)
        if not task.done():
            await self._abandon(task)

    # ------------------------------------------------------------------ events / pause state
    def _emit(self, type_: EventType, **extra: object) -> None:
        self._bus.publish(
            type_,
            {
                "session_id": self._session_id,
                "frames_done": self._frames_done,
                "sets_done": self._sets_done,
                "failures": self._failures,
                **extra,
            },
        )

    def _warn(self, code: str, message: str, **extra: object) -> None:
        log.warning("timelapse %s: %s", code, message)
        self._emit(EventType.TIMELAPSE_WARNING, code=code, message=message, **extra)

    async def _sync_pause_state(self) -> None:
        if self._state not in (TimelapseState.RUNNING, TimelapseState.PAUSED):
            return
        paused = self._user_pause or self._cam_pause
        want = TimelapseState.PAUSED if paused else TimelapseState.RUNNING
        if want == self._state:
            return
        self._state = want
        sid = self._session_id
        if paused:
            self._emit(EventType.TIMELAPSE_PAUSED, reason=self._pause_reason())
        else:
            self._emit(EventType.TIMELAPSE_RESUMED)
        if sid:
            status = SessionStatus.PAUSED if paused else SessionStatus.RUNNING
            await self._sessions.update(sid, status=status)

    def _camera_ok(self) -> bool:
        return self._camera.status().connected

    async def _set_cam_pause(self, why: str) -> None:
        if self._cam_pause:
            return
        self._cam_pause = True
        self._warn("camera_disconnected", f"Camera unavailable, pausing: {why}")
        await self._sync_pause_state()

    async def _wait(self, delay: float, wake: asyncio.Event) -> None:
        """Sleep ``delay`` (injected sleep) or until ``wake`` is set."""
        if delay <= 0 or wake.is_set():
            return
        sleeper = asyncio.ensure_future(self._sleep(delay))
        waker = asyncio.ensure_future(wake.wait())
        try:
            await asyncio.wait({sleeper, waker}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (sleeper, waker):
                t.cancel()
            await asyncio.gather(sleeper, waker, return_exceptions=True)

    # ------------------------------------------------------------------ the run
    async def _run(self, r: ResolvedConfig) -> None:
        final = TimelapseState.COMPLETED
        cancelled = False
        try:
            await self._main(r)
            if self._stop_req:
                final = TimelapseState.STOPPED
        except _RunFailed as e:
            final, self._error = TimelapseState.FAILED, str(e)
        except asyncio.CancelledError:
            final, cancelled = TimelapseState.STOPPED, True
        except Exception as e:
            log.exception("time-lapse runner crashed")
            final, self._error = TimelapseState.FAILED, f"Unexpected error: {e}"
        await self._finish(final, cancelled)

    async def _finish(self, final: TimelapseState, cancelled: bool) -> None:
        # Settings go back first, then the lease is released, then the state becomes terminal.
        try:
            await self._stop_watcher()
            try:
                await self._await_camera_for_restore()
                if self._dirty and self._camera_ok() and not self._restore_hung:
                    await self._restore_bounded()
                if self._dirty:
                    self._warn(
                        "settings_not_restored",
                        "Camera settings could not be restored: "
                        + ", ".join(f"{k}={v}" for k, v in self._snapshot.items()),
                    )
            except Exception:
                log.exception("restoring camera settings failed")
        finally:
            await self._release_lease()  # always, even when cancelled again
        if self._started_mono is not None:
            self._finished_elapsed = max(0.0, self._clock() - self._started_mono)
        self._next_at = None
        self._user_pause = self._cam_pause = False
        interrupted = self._shutdown or cancelled
        status = SessionStatus.INTERRUPTED if interrupted else _SESSION_STATUS[final]
        error = self._error or ("Interrupted by application shutdown" if interrupted else None)
        if self._session_id:
            try:
                await self._sessions.update(
                    self._session_id,
                    status=status,
                    finished=datetime.now(UTC),
                    error=error,
                    frames_failed=self._failures,
                )
            except Exception:
                log.exception("updating session %s failed", self._session_id)
        self._state = final
        if final == TimelapseState.COMPLETED:
            self._emit(EventType.TIMELAPSE_COMPLETED)
        elif final == TimelapseState.FAILED:
            self._emit(EventType.TIMELAPSE_ERROR, error=self._error)
        else:
            self._emit(EventType.TIMELAPSE_STOPPED, interrupted=interrupted)

    async def _release_lease(self) -> None:
        stack, self._stack = self._stack, None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                log.exception("releasing camera lease failed")

    async def _stop_watcher(self) -> None:
        sub, self._sub = self._sub, None
        watcher, self._watcher = self._watcher, None
        if sub is not None:
            sub.close()
        if watcher is not None and watcher is not asyncio.current_task():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def _watch_camera(self, sub: Subscription) -> None:
        """React to camera connect/disconnect events at once (no waiting for the next shot)."""
        async for ev in sub:
            if ev.type == EventType.CAMERA_DISCONNECTED:
                await self._set_cam_pause("camera disconnected")
                self._wake.set()
            elif ev.type == EventType.CAMERA_CONNECTED:
                await self._try_rejoin()
                self._wake.set()

    async def _await_camera_for_restore(self) -> None:
        """Real-time grace period for the camera to come back before giving up on restoring."""
        deadline = time.monotonic() + RECONNECT_WAIT_S
        while self._dirty and not self._shutdown and not self._camera_ok():
            if time.monotonic() > deadline:
                return
            await asyncio.sleep(0.05)

    async def _main(self, r: ResolvedConfig) -> None:
        interval = r.config.interval_s
        anchor = self._clock()
        k = 0
        if r.config.duration_s is not None:
            self._deadline = anchor + r.config.duration_s
        while True:
            self._wake.clear()
            if self._stop_req:
                return
            if not self._camera_ok():
                await self._set_cam_pause("not connected")
            if self._user_pause or self._cam_pause:
                held = self._clock()
                await self._hold()
                if self._stop_req:
                    return
                now = self._clock()
                if self._deadline is not None:
                    self._deadline += now - held
                anchor, k = now, 0  # resume re-anchors: the next set is due immediately
                continue
            if self._dirty:
                await self._restore_bounded()
            if self._sets_done >= r.total_sets:
                return
            target = anchor + k * interval
            if self._deadline is not None and target >= self._deadline - _EPS:
                return
            now = self._clock()
            if now < target:
                self._next_at = target
                await self._wait(target - now, self._wake)
                continue
            self._next_at = None
            set_start = self._clock()
            completed = await self._do_set(r)
            if not completed:
                continue  # stop, disconnect or pause: handled at the top
            self._sets_done += 1
            k += 1
            end = self._clock()
            self._track_duration(end - set_start, interval)
            if end > anchor + k * interval + _EPS:
                k_new = math.ceil((end - anchor) / interval - _EPS)
                self._warn(
                    "overrun",
                    f"Set took longer than the {interval:g}s interval; skipping slots",
                    skipped_slots=k_new - k,
                )
                k = k_new

    def _track_duration(self, took: float, interval: float) -> None:
        """Rolling average of real set durations; ONE warning when it exceeds the interval."""
        self._durations.append(took)
        measured = self._measured()
        if (
            measured is not None
            and len(self._durations) >= MIN_RATE_SAMPLES
            and measured > interval
            and not self._slow_warned
        ):
            self._slow_warned = True
            self._warn(
                "interval_too_short",
                f"Sets take {measured:g}s on average, longer than the {interval:g}s interval",
                measured_set_duration_s=measured,
                suggested_min_interval_s=math.ceil(measured * 1.1 * 10) / 10,
            )

    async def _hold(self) -> None:
        """Park until neither the user nor a missing camera holds the run back."""
        while True:
            self._wake.clear()
            if self._stop_req:
                return
            await self._try_rejoin()
            if not self._user_pause and not self._cam_pause:
                return
            if self._cam_pause:
                await self._wait(CAMERA_POLL_S, self._wake)
            else:
                await self._wake.wait()

    async def _try_rejoin(self) -> None:
        """Camera back: re-take the lease first, only then lift the camera pause. If another
        owner got the lease in between, stay paused (warn once) rather than shoot without it."""
        if not self._cam_pause or self._stop_req or not self._camera_ok():
            return
        if await self._reacquire_lease():
            self._cam_pause = False
            self._lease_warned = False
            await self._sync_pause_state()
        elif not self._lease_warned:
            self._lease_warned = True
            holder = self._camera.status().leased_by
            self._warn(
                "lease_lost",
                f"Camera is back but leased by {holder!r}; staying paused until it is free",
                leased_by=holder,
            )

    async def _reacquire_lease(self) -> bool:
        if self._camera.status().leased_by == OWNER:
            return True
        if self._camera.status().leased_by is not None or self._stack is None:
            return False
        try:
            await self._stack.enter_async_context(self._camera.lease(OWNER))
        except CameraBusy:
            return False
        return True

    async def _ensure_lease(self) -> None:
        if not await self._reacquire_lease():
            holder = self._camera.status().leased_by
            raise _RunFailed(f"Camera is leased by {holder!r}")

    async def _restore(self) -> None:
        """Put the snapshot back; stays ``dirty`` (retried later) if the camera refuses."""
        try:
            await self._ensure_lease()
            await self._settings.restore(self._snapshot, owner=OWNER)
        except _RunFailed:
            raise
        except Exception as e:
            self._warn("restore_failed", f"Could not restore camera settings: {e}")
            return
        self._dirty = False

    async def _restore_bounded(self) -> None:
        """``_restore`` with a deadline: a hung camera must not hang stop/shutdown again."""
        try:
            await asyncio.wait_for(self._restore(), RESTORE_TIMEOUT_S)
        except TimeoutError:
            self._restore_hung = True
            self._warn("restore_failed", "Restoring camera settings timed out")

    async def _do_set(self, r: ResolvedConfig) -> bool:
        """One interval: every step of the bracket (or the single shot). True when all steps
        were attempted; False when stopped or cut short by a camera disconnect."""
        folder = self._sessions.folder(self._session_id or "")
        self._set_seq += 1
        set_index = self._set_seq - 1
        plan: list[BracketStep | None] = list(r.steps) or [None]
        try:
            for i, step in enumerate(plan):
                if self._stop_req:
                    return False
                if step is not None and step.delay_ms:
                    await self._wait(step.delay_ms / 1000, self._stop_wake)
                    if self._stop_req:
                        return False
                try:
                    await self._ensure_lease()
                    if step is not None:
                        self._dirty = True
                        await self._settings.set_many(step.settings, owner=OWNER)
                        await self._wait(SETTLE_S, self._stop_wake)
                    prefix = (
                        f"s{set_index:05d}-{i:02d}-" if step is not None else f"f{set_index:05d}-"
                    )
                    paths = await self._capture.capture_to(folder, owner=OWNER, name_prefix=prefix)
                    if not paths:
                        raise AppError("Camera returned no files")
                    await self._record(folder, paths, set_index, i, step)
                except asyncio.CancelledError:
                    raise
                except _RunFailed:
                    raise
                except Exception as e:
                    if _is_disk_full(e):
                        raise _RunFailed(f"Storage full: {e}") from e
                    if isinstance(e, CameraBusy):
                        raise _RunFailed("Camera is busy with another owner") from e
                    await self._record_failure(e)  # budget applies to disconnects too
                    if not self._camera_ok():
                        await self._set_cam_pause(str(e))
                        return False
            return True
        finally:
            if self._dirty:
                await self._restore_bounded()

    async def _record(
        self,
        folder: Path,
        paths: list[Path],
        set_index: int,
        step_index: int,
        step: BracketStep | None,
    ) -> None:
        files: list[SessionFile] = []
        for p in paths:
            size = (await asyncio.to_thread(p.stat)).st_size
            ext = p.suffix.lower()
            kind = "raw" if ext in RAW_EXTS else "jpeg" if ext in (".jpg", ".jpeg") else "other"
            files.append(
                SessionFile(path=p.relative_to(folder).as_posix(), kind=kind, size=size)  # type: ignore[arg-type]
            )
        now = datetime.now(UTC)
        index = self._frames_done
        frame = SessionFrame(
            index=index,
            captured_at=now,
            files=files,
            bracket=(
                BracketInfo(step_index=step_index, label=step.label, settings=dict(step.settings))
                if step is not None
                else None
            ),
            set_index=set_index,
        )
        await self._sessions.add_frame(self._session_id or "", frame)
        self._frames_done += 1
        self._consecutive = 0
        self._last_frame = LastFrame(
            index=index, set_index=set_index, files=[f.path for f in files], captured_at=now
        )
        self._emit(EventType.TIMELAPSE_FRAME, index=index, set_index=set_index, step=step_index)

    async def _record_failure(self, e: Exception) -> None:
        self._failures += 1
        self._consecutive += 1
        msg = getattr(e, "message", None) or str(e) or type(e).__name__
        self._warn(
            "frame_failed",
            f"Frame failed: {msg}",
            consecutive_failures=self._consecutive,
        )
        if self._session_id:
            with contextlib.suppress(Exception):
                await self._sessions.update(self._session_id, frames_failed=self._failures)
        if self._consecutive >= self._budget:
            raise _RunFailed(
                f"{self._consecutive} consecutive capture failures (budget {self._budget}); "
                f"last error: {msg}"
            )
