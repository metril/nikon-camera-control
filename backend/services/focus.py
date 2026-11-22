"""Focus control (autofocus, manual focus drive) and focus stacking.

Driven through ``manualfocusdrive`` / ``autofocusdrive``, which are deliberately not in the
settings allowlist. The lens reports no absolute position, so position is tracked relative to
an origin the user can reset. Manual drive needs live view on Nikon bodies: every move
enables the viewfinder first if it is off and restores IDLE afterwards if it had to enter live view.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.camera.backend import ConfigWidget
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraNotConnected,
    FeatureUnsupported,
    InvalidState,
    SettingInvalid,
)
from backend.core.jobs import HeldContext, Job, JobContext, JobManager
from backend.core.state import CameraState
from backend.services.capture import CaptureService
from backend.services.storage import sanitize_name

log = logging.getLogger(__name__)

OWNER = "focus-stack"
JOB_KIND = "focus-stack"
RETURN_TIMEOUT_S = 60.0
DRIVE_WAIT_S = 30.0  # bound on waiting for an in-flight drive after a cancel
_S = CameraState
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")

Sleep = Callable[[float], Awaitable[object]]


class FocusService:
    def __init__(
        self,
        camera: CameraService,
        capture: CaptureService,
        jobs: JobManager,
        output_dir: Path,
        *,
        sleep: Sleep = asyncio.sleep,
        return_timeout_s: float = RETURN_TIMEOUT_S,
    ) -> None:
        self._camera = camera
        self._capture = capture
        self._jobs = jobs
        self._output = output_dir
        self._sleep = sleep
        self._return_timeout = return_timeout_s
        self._lock = asyncio.Lock()
        self._pos = 0
        self._last_af_at: datetime | None = None
        self._range: tuple[int, int, int] | None = None

    @property
    def relative_position(self) -> int:
        return self._pos

    @property
    def last_af_at(self) -> datetime | None:
        return self._last_af_at

    def reset(self) -> int:
        self._pos = 0
        return 0

    def _require_free(self, owner: str | None) -> None:
        st = self._camera.status()
        if not st.connected:
            raise CameraNotConnected()
        if st.leased_by is not None and st.leased_by != owner:
            raise CameraBusy(details={"leased_by": st.leased_by})

    async def get_range(self) -> tuple[int, int, int]:
        """(min, max, step) of ``manualfocusdrive``; cached. Read at KEEPALIVE priority so it
        works while a lease is held."""
        if self._range is None:
            w: ConfigWidget = await self._camera.call(
                lambda b: b.get_config("manualfocusdrive"), priority=Priority.KEEPALIVE
            )
            if w.range is None:
                raise FeatureUnsupported("Camera reports no manual focus range")
            self._range = (int(w.range.min), int(w.range.max), max(1, int(w.range.step)))
        return self._range

    async def autofocus(self) -> bool | None:
        """Trigger AF. A failed lock raises the backend's CameraOperationFailed (the link is
        fine; only genuine USB loss disconnects)."""
        self._require_free(None)
        async with self._lock:
            await self._camera.call(
                lambda b: b.set_config("autofocusdrive", 1), priority=Priority.CONTROL
            )
        self._last_af_at = datetime.now(UTC)
        return True

    async def move(self, steps: int, *, owner: str | None = None) -> int:
        """Drive focus by ``steps`` (signed); returns the new relative position."""
        lo, hi, step = await self.get_range()
        if steps == 0 or not lo <= steps <= hi or (steps - lo) % step:
            raise SettingInvalid(
                f"steps must be non-zero and within [{lo}, {hi}]",
                details={"steps": steps, "min": lo, "max": hi, "step": step},
            )
        self._require_free(owner)
        async with self._lock:
            prior = self._camera.state
            if prior not in (_S.IDLE, _S.LIVEVIEW):
                raise InvalidState(f"Cannot focus while camera is {prior.value}")
            entered = prior == _S.IDLE
            if entered:
                await self._camera.transition(_S.LIVEVIEW)
            try:

                def _drive(b: Any) -> None:
                    # a capture may have switched the viewfinder off; only enable it when off
                    # (some bodies answer busy to a redundant viewfinder=1)
                    try:
                        on = bool(b.get_config("viewfinder").value)
                    except AppError:
                        on = False
                    if not on:
                        b.set_config("viewfinder", 1)
                    b.set_config("manualfocusdrive", steps)

                await self._drive_tracked(_drive, steps, owner)
            finally:
                if entered and self._camera.state == _S.LIVEVIEW:
                    with contextlib.suppress(AppError):
                        await self._camera.transition(_S.IDLE)
        return self._pos

    async def _drive_tracked(
        self, drive: Callable[[Any], None], steps: int, owner: str | None
    ) -> None:
        """Run the drive as an independent task: a cancel cannot withdraw it from the camera, so
        the position is updated when it succeeds, whatever happens to the caller. After a cancel
        we wait (bounded) for it so the position is right before any return-to-start."""
        task = asyncio.ensure_future(
            self._camera.call(drive, priority=Priority.CONTROL, owner=owner)
        )

        def account(t: asyncio.Future[Any]) -> None:
            if not t.cancelled() and t.exception() is None:
                self._pos += steps

        task.add_done_callback(account)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait({task}, timeout=DRIVE_WAIT_S)
            raise

    # stacking ---------------------------------------------------------------------
    async def start_stack(
        self,
        *,
        steps_per_shot: int,
        shots: int,
        direction: str,
        settle_ms: int,
        return_to_start: bool,
        name: str | None,
    ) -> Job:
        self._require_free(None)
        sign = 1 if direction == "near_to_far" else -1
        delta = sign * steps_per_shot
        lo, hi, step = await self.get_range()
        if not lo <= delta <= hi or (delta - lo) % step:
            raise SettingInvalid(
                f"steps_per_shot must move focus within [{lo}, {hi}] in steps of {step}",
                details={"steps": delta, "min": lo, "max": hi, "step": step},
            )

        async def factory(ctx: JobContext) -> dict[str, Any]:
            try:
                return await self._run_stack(
                    ctx, delta, shots, settle_ms / 1000, return_to_start, name
                )
            finally:
                await held.release()

        held = HeldContext(self._camera.lease(OWNER))
        await held.enter()  # 409 now, not inside the job
        try:
            return self._jobs.submit(
                JOB_KIND, factory, exclusive_key=JOB_KIND, release=held.release
            )
        except BaseException:
            await held.release()
            raise

    def _make_dest(self, name: str | None) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = sanitize_name(_SAFE.sub("_", name or ""), default="").strip("_")
        base = self._output / "stacks"
        base.mkdir(parents=True, exist_ok=True)
        stem = f"{stamp}-{label}" if label else stamp
        dest, n = base / stem, 1
        while True:
            try:
                dest.mkdir()
                return dest
            except FileExistsError:
                n += 1
                dest = base / f"{stem}-{n}"

    async def _run_stack(
        self,
        ctx: JobContext,
        delta: int,
        shots: int,
        settle_s: float,
        return_to_start: bool,
        name: str | None,
    ) -> dict[str, Any]:
        prior = self._camera.state
        start_pos = self._pos
        dest = await asyncio.to_thread(self._make_dest, name)
        folder = dest.relative_to(self._output).as_posix()
        files = moves = 0
        try:
            for i in range(shots):
                if ctx.cancelled:
                    break
                ctx.report(i / shots, f"Shot {i + 1}/{shots}")
                paths = await self._capture.capture_to(
                    dest, owner=OWNER, name_prefix=f"{i + 1:03d}_"
                )
                files += len(paths)
                if i < shots - 1:
                    await self.move(delta, owner=OWNER)
                    moves += 1
                    await self._sleep(settle_s)
        finally:
            await self._cleanup(return_to_start, start_pos, prior)
        return {
            "folder": folder,
            "file_count": files,
            "total_steps_moved": moves * abs(delta),
            "returned_to_start": return_to_start and self._pos == start_pos,
            "net_steps": self._pos - start_pos,
        }

    async def _cleanup(self, return_to_start: bool, start_pos: int, prior: CameraState) -> None:
        """Bounded, best effort; never masks the original outcome."""
        try:
            async with asyncio.timeout(self._return_timeout):
                lo, hi, _ = await self.get_range()
                while return_to_start and (back := start_pos - self._pos):
                    await self.move(max(lo, min(hi, back)), owner=OWNER)
                state = self._camera.state
                if prior == _S.LIVEVIEW and state == _S.IDLE:
                    await self._camera.transition(_S.LIVEVIEW)
                elif prior == _S.IDLE and state == _S.LIVEVIEW:
                    await self._camera.transition(_S.IDLE)
        except (AppError, TimeoutError) as e:
            log.warning("focus stack cleanup incomplete: %s", e)
