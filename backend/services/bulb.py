"""Bulb (long exposure): shutterspeed=Bulb, bulb=1 ... wait ... bulb=0, collect and download.

D500-UNVERIFIED assumptions (developed against FakeCamera):
- ``bulb`` is a toggle writable as 1/0 over PTP. libgphoto2's ``_put_Nikon_Bulb`` may itself
  switch to M / bulb time, so the M-mode and "Bulb" shutter-speed checks are best effort:
  a non-M mode only adds a warning (and a hint if the open then fails).
- Closing the shutter makes the image arrive as a FILE_ADDED event (not from ``capture()``).
- Long-exposure noise reduction delays that event by about the exposure time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.api.schemas.common import EventType
from backend.api.schemas.exposure import BulbRequest, BulbStatus
from backend.camera.backend import CameraBackend, CameraFilePath
from backend.camera.backend import EventType as CamEventType
from backend.core.camera_service import CameraService, Priority, drain_pending_events
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraNotConnected,
    CameraOperationFailed,
    InvalidState,
    ShutterOpen,
)
from backend.core.events import EventBus
from backend.core.jobs import HeldContext, Job, JobContext, JobManager
from backend.core.state import CameraState
from backend.core.storage_root import StorageRoot, as_root
from backend.services.capture import sanitize_prefix
from backend.services.storage import download_files

log = logging.getLogger(__name__)

OWNER = "bulb"
CLOSE_ATTEMPTS = 4
CLOSE_RETRY_DELAY_S = 0.25
CLOSE_WAIT_S = 90.0  # bound on a shielded close sequence
CANCEL_COLLECT_GRACE_S = 5.0  # after a cancel, how long to wait for a frame still in flight
_MANUAL = frozenset({"M", "MANUAL"})
MODE_NAMES = ("expprogram", "autoexposuremode")  # widget names for the exposure program


@dataclass
class _Run:
    job_id: str
    seconds: float
    started: float | None = None  # clock value when the shutter opened
    ended: float | None = None
    files: list[CameraFilePath] = field(default_factory=list)


class BulbService:
    def __init__(
        self,
        camera: CameraService,
        jobs: JobManager,
        bus: EventBus,
        output_dir: Path | StorageRoot,
        invalidate_index: Callable[[], None],
        *,
        quiet_window_s: float = 1.0,
        default_prefix: Callable[[], str | None] = lambda: None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._camera = camera
        self._jobs = jobs
        self._bus = bus
        self._store = as_root(output_dir)
        self._invalidate = invalidate_index
        self._quiet = quiet_window_s
        self._default_prefix = default_prefix
        self._sleep = sleep
        self._clock = clock
        self._run: _Run | None = None

    # ---- public ----
    def status(self) -> BulbStatus:
        r = self._run
        if r is None:
            return BulbStatus(active=False)
        end = r.ended if r.ended is not None else self._clock()
        elapsed = 0.0 if r.started is None else max(0.0, min(r.seconds, end - r.started))
        remaining = r.seconds if r.started is None else max(0.0, r.seconds - elapsed)
        return BulbStatus(
            active=True,
            job_id=r.job_id,
            seconds=r.seconds,
            elapsed_s=round(elapsed, 3),
            remaining_s=round(remaining, 3),
        )

    async def start(self, req: BulbRequest) -> Job:
        """Preflight (connected, IDLE, not leased), take the lease, then submit the job."""
        st = self._camera.status()
        if not st.connected:
            raise CameraNotConnected()
        if st.leased_by is not None:
            raise CameraBusy(details={"leased_by": st.leased_by})
        if st.state != CameraState.IDLE:
            raise InvalidState(
                f"Bulb needs an idle camera (state is {st.state.value}); stop live view first",
                details={"state": st.state.value},
            )
        if req.download:
            self._store.root()  # NoTargetError (409) before the shutter opens
        held = HeldContext(self._camera.lease(OWNER))
        await held.enter()  # 409 now, not inside the job
        try:
            return self._jobs.submit(
                "bulb",
                lambda ctx: self._job(ctx, req, held),
                exclusive_key="bulb",
                release=held.release,
            )
        except BaseException:
            await held.release()
            raise

    # ---- job ----
    async def _expprogram_warning(self) -> str | None:
        try:
            name = await self._camera.resolve_setting("bulb-mode", MODE_NAMES)
            prog = await self._camera.refresh_setting(name)
        except AppError as e:
            log.info("could not read the exposure program: %s", e.message)
            return None
        if str(prog.value).strip().upper() in _MANUAL:
            return None
        how = (
            "turn the mode dial to M"
            if prog.readonly
            else f"set the exposure program ({name}) to M in Settings or on the mode dial"
        )
        return f"Exposure program is {prog.value!r}, not M; bulb usually needs M ({how})."

    async def _prepare_speed(self) -> str | None:
        """Best effort: select shutterspeed 'Bulb' if offered. Returns the value to restore."""
        try:
            speed = await self._camera.refresh_setting("shutterspeed")
            prior = str(speed.value)
            if "Bulb" not in speed.choices or prior == "Bulb":
                return None
            await self._camera.set_setting("shutterspeed", "Bulb", owner=OWNER)
            return prior
        except AppError as e:
            log.info("could not pre-select Bulb shutter speed: %s", e.message)
            return None

    async def _open(self, run: _Run) -> asyncio.CancelledError | None:
        """bulb=1, shielded: a cancelled camera.call does not withdraw its queued item, so we
        always let it finish and let the caller close. Returns a cancellation, if any."""
        task = asyncio.ensure_future(self._set_bulb(1))
        cancel: asyncio.CancelledError | None = None
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError as e:
                if task.cancelled():
                    raise
                cancel = e  # ours: keep waiting for the in-flight open
        run.started = self._clock()
        return cancel

    async def _job(self, ctx: JobContext, req: BulbRequest, held: HeldContext) -> dict[str, Any]:
        run = self._run = _Run(ctx.job_id, req.seconds)
        cam = self._camera
        prior_speed: str | None = None
        opened = False
        cancel: asyncio.CancelledError | None = None
        result: dict[str, Any] = {}
        warnings: list[str] = []
        try:
            prior_state = await cam.transition(CameraState.BULB)
            try:
                if (w := await self._expprogram_warning()) is not None:
                    warnings.append(w)
                prior_speed = await self._prepare_speed()
                self._bus.publish(
                    EventType.CAPTURE_STARTED,
                    {"bulb": True, "seconds": req.seconds, "warnings": warnings},
                )
                # Strays from earlier trigger-only or body shots are not this exposure's frame.
                await cam.call(
                    lambda b: drain_pending_events(b), priority=Priority.CAPTURE, owner=OWNER
                )
                opened = True  # before issuing: a redundant close is harmless, a missed one is not
                try:
                    cancel = await self._open(run)
                except AppError as e:
                    hint = " Bulb usually needs exposure program M." if warnings else ""
                    raise CameraOperationFailed(
                        f"Could not open the shutter: {e.message.rstrip('.')}.{hint}",
                        details={"cause": e.message, "warnings": warnings},
                    ) from e
                if cancel is None:
                    cancel = await self._wait_exposure(ctx, run)
                if (recancel := await self._close_shielded(run)) is not None:
                    cancel = cancel or recancel
                opened = False  # only after a close succeeded
                files, collect_cancel = await self._collect(ctx, req.seconds, cancel is not None)
                cancel = cancel or collect_cancel
                run.files = files
                if not files and cancel is not None:
                    raise cancel
                result = await self._finish_files(files, req)
                result["warnings"] = warnings
                self._bus.publish(
                    EventType.CAPTURE_COMPLETE,
                    {
                        "bulb": True,
                        "files": [{"folder": f.folder, "name": f.name} for f in files],
                    },
                )
            finally:
                if opened:
                    await self._emergency_close(run)
                await self._restore(prior_speed)
                if cam.state == CameraState.BULB:
                    await cam.transition(prior_state)
        finally:
            self._run = None
            await held.release()
        if cancel is not None:
            raise cancel
        return result

    async def _wait_exposure(self, ctx: JobContext, run: _Run) -> asyncio.CancelledError | None:
        """Wait out the exposure, reporting remaining seconds. Returns the cancellation, if any
        (the caller closes the shutter and keeps the frame before re-raising it)."""
        started = run.started if run.started is not None else self._clock()
        try:
            while True:
                elapsed = self._clock() - started
                left = run.seconds - elapsed
                ctx.report(
                    min(1.0, elapsed / run.seconds) * 0.8, f"{max(0.0, left):.0f}s remaining"
                )
                if left <= 0:
                    return None
                await self._sleep(min(1.0, left))
        except asyncio.CancelledError as e:
            return e

    async def _set_bulb(self, value: int) -> None:
        await self._camera.call(
            lambda b: b.set_config("bulb", value), priority=Priority.CAPTURE, owner=OWNER
        )

    async def _close(self, run: _Run) -> None:
        """bulb=0 with retries; if the shutter cannot be closed shout and flag the camera."""
        last: AppError | None = None
        for attempt in range(CLOSE_ATTEMPTS):
            try:
                await self._set_bulb(0)
                run.ended = self._clock()
                if attempt:
                    log.warning("bulb close succeeded on attempt %d", attempt + 1)
                return
            except AppError as e:
                last = e
                log.error("bulb close attempt %d failed: %s", attempt + 1, e.message)
                if attempt < CLOSE_ATTEMPTS - 1:
                    await self._sleep(CLOSE_RETRY_DELAY_S)
        msg = "COULD NOT CLOSE THE SHUTTER: the bulb exposure may still be open. Check the camera."
        self._bus.publish(
            EventType.ERROR,
            {"code": "BULB_SHUTTER_OPEN", "message": msg, "cause": last.message if last else ""},
        )
        if self._camera.state == CameraState.BULB:
            await self._camera.transition(CameraState.ERROR)
        raise ShutterOpen(msg, details={"cause": last.message if last else ""})

    async def _close_shielded(self, run: _Run) -> asyncio.CancelledError | None:
        """Run the close sequence to completion even if this task is cancelled again (bounded
        by CLOSE_WAIT_S). Returns the cancellation, if any; raises if the close failed."""
        task = asyncio.ensure_future(self._close(run))
        cancel: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.wait({task}, timeout=CLOSE_WAIT_S)
                break
            except asyncio.CancelledError as e:
                cancel = e
        if not task.done():
            log.error("bulb close did not finish within %.0fs", CLOSE_WAIT_S)
            raise ShutterOpen("COULD NOT CONFIRM THE SHUTTER CLOSED: check the camera.")
        task.result()
        return cancel

    async def _emergency_close(self, run: _Run) -> None:
        """Cleanup close while an error propagates; shielded against further cancels."""
        try:
            await self._close_shielded(run)
        except Exception:
            log.exception("emergency bulb close failed")

    async def _collect(
        self, ctx: JobContext, seconds: float, cancelled: bool
    ) -> tuple[list[CameraFilePath], asyncio.CancelledError | None]:
        """Drain camera events until a FILE_ADDED has been followed by a quiet window, or the
        deadline (exposure + noise reduction) passes. After a cancel, give a frame that is
        still in flight only CANCEL_COLLECT_GRACE_S. Cancellation never loses a frame that
        already arrived."""
        started = time.monotonic()
        deadline = started + seconds + 60.0
        files: list[CameraFilePath] = []
        last: float | None = None
        cancel: asyncio.CancelledError | None = None
        if cancelled or ctx.cancelled:
            deadline = min(deadline, started + CANCEL_COLLECT_GRACE_S)
        while True:
            now = time.monotonic()
            if now >= deadline or (last is not None and now - last >= self._quiet):
                break
            if cancel is None and ctx.cancelled:
                deadline = min(deadline, now + CANCEL_COLLECT_GRACE_S)
            try:
                ev = await self._camera.call(
                    lambda b: self._poll(b), priority=Priority.CAPTURE, owner=OWNER, timeout=10.0
                )
            except asyncio.CancelledError as e:
                cancel = e
                deadline = min(deadline, time.monotonic() + CANCEL_COLLECT_GRACE_S)
                continue
            except AppError as e:
                log.warning("bulb collect poll failed: %s", e.message)
                break
            if ev is not None:
                last = time.monotonic()
                if ev not in files:
                    files.append(ev)
        return files, cancel

    @staticmethod
    def _poll(b: CameraBackend) -> CameraFilePath | None:
        ev = b.wait_for_event(0.25)
        if ev.type == CamEventType.FILE_ADDED and ev.file is not None:
            return ev.file
        return None

    async def _finish_files(self, files: list[CameraFilePath], req: BulbRequest) -> dict[str, Any]:
        if not files:
            raise CameraOperationFailed(
                "Shutter closed but no image arrived from the camera",
                details={"seconds": req.seconds},
            )
        local: list[Path] = []
        if req.download:
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S-")
            prefix = sanitize_prefix(req.filename_prefix or self._default_prefix())
            try:
                local = await download_files(
                    self._camera,
                    files,
                    self._store.root(),
                    owner=OWNER,
                    name_prefix=f"{prefix}{stamp}",
                    on_stored=self._store.stored,
                )
            finally:
                self._invalidate()
        root = self._store.root().resolve()
        return {
            "seconds": req.seconds,
            "files": [p.resolve().relative_to(root).as_posix() for p in local],
            "camera_files": [f"{f.folder}/{f.name}" for f in files],
        }

    async def _restore(self, prior_speed: str | None) -> None:
        if prior_speed is None or prior_speed == "Bulb":
            return
        try:
            await asyncio.shield(self._camera.set_setting("shutterspeed", prior_speed, owner=OWNER))
        except Exception:
            log.exception("could not restore shutterspeed %r", prior_speed)
            self._bus.publish(
                EventType.ERROR,
                {
                    "code": "BULB_RESTORE_FAILED",
                    "message": f"Shutter speed left on Bulb; was {prior_speed!r}",
                },
            )
