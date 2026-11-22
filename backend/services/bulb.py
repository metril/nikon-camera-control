"""Bulb (long exposure): shutterspeed=Bulb, bulb=1 ... wait ... bulb=0, collect and download.

D500-UNVERIFIED assumptions (developed against FakeCamera):
- ``expprogram`` reads "M" in manual mode (also accepts "Manual").
- ``shutterspeed`` has a "Bulb" choice and ``bulb`` is a toggle writable as 1/0 over PTP.
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
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraNotConnected,
    CameraOperationFailed,
    FeatureUnsupported,
    InvalidState,
)
from backend.core.events import EventBus
from backend.core.jobs import Job, JobContext, JobManager
from backend.core.state import CameraState
from backend.services.capture import sanitize_prefix
from backend.services.storage import download_files

log = logging.getLogger(__name__)

OWNER = "bulb"
CLOSE_ATTEMPTS = 4
CLOSE_RETRY_DELAY_S = 0.25
_MANUAL = frozenset({"M", "MANUAL"})


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
        output_dir: Path,
        invalidate_index: Callable[[], None],
        *,
        quiet_window_s: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._camera = camera
        self._jobs = jobs
        self._bus = bus
        self._output = output_dir
        self._invalidate = invalidate_index
        self._quiet = quiet_window_s
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
        """Preflight (connected, IDLE, not leased, M mode), then submit the job."""
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
        await self._check_manual()
        return self._jobs.submit("bulb", lambda ctx: self._job(ctx, req), exclusive_key="bulb")

    # ---- job ----
    async def _check_manual(self) -> None:
        prog = await self._camera.refresh_setting("expprogram")
        if str(prog.value).strip().upper() not in _MANUAL:
            raise InvalidState(
                f"Bulb needs exposure program M; the camera is in {prog.value!r}. "
                "Turn the mode dial to M (it cannot be set remotely).",
                details={"expprogram": prog.value},
            )

    async def _job(self, ctx: JobContext, req: BulbRequest) -> dict[str, Any]:
        run = self._run = _Run(ctx.job_id, req.seconds)
        cam = self._camera
        prior_speed: str | None = None
        opened = False
        cancel: asyncio.CancelledError | None = None
        result: dict[str, Any] = {}
        try:
            async with cam.lease(OWNER):
                prior_state = await cam.transition(CameraState.BULB)
                try:
                    await self._check_manual()
                    speed = await cam.refresh_setting("shutterspeed")
                    if "Bulb" not in speed.choices:
                        raise FeatureUnsupported(
                            "Camera offers no 'Bulb' shutter speed",
                            details={"choices": list(speed.choices)[:40]},
                        )
                    prior_speed = str(speed.value)
                    if prior_speed != "Bulb":
                        await cam.set_setting("shutterspeed", "Bulb", owner=OWNER)
                    self._bus.publish(
                        EventType.CAPTURE_STARTED, {"bulb": True, "seconds": req.seconds}
                    )
                    await self._set_bulb(1)
                    opened = True
                    run.started = self._clock()
                    cancel = await self._wait_exposure(ctx, run)
                    try:
                        await self._close(run)
                    finally:
                        opened = False  # _close already retried and raised loudly
                    files = await self._collect(req.seconds)
                    run.files = files
                    result = await self._finish_files(files, req)
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
        raise CameraOperationFailed(msg, details={"cause": last.message if last else ""})

    async def _emergency_close(self, run: _Run) -> None:
        """Cleanup close while an error propagates; shielded against a second cancel."""
        try:
            await asyncio.shield(self._close(run))
        except Exception:
            log.exception("emergency bulb close failed")

    async def _collect(self, seconds: float) -> list[CameraFilePath]:
        """Drain camera events until a FILE_ADDED has been followed by a quiet window, or the
        generous deadline (exposure + noise reduction) passes. Empty list on timeout."""
        deadline = time.monotonic() + seconds * 1.5 + 30.0
        files: list[CameraFilePath] = []
        last: float | None = None
        while True:
            now = time.monotonic()
            if now >= deadline or (last is not None and now - last >= self._quiet):
                break
            ev = await self._camera.call(
                lambda b: self._poll(b), priority=Priority.CAPTURE, owner=OWNER, timeout=10.0
            )
            if ev is not None:
                last = time.monotonic()
                if ev not in files:
                    files.append(ev)
        return files

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
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
            try:
                local = await download_files(
                    self._camera,
                    files,
                    self._output,
                    owner=OWNER,
                    name_prefix=f"{sanitize_prefix(req.filename_prefix)}{stamp}",
                )
            finally:
                self._invalidate()
        root = self._output.resolve()
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
