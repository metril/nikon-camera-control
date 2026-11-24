"""Focus control (autofocus, manual focus drive) and focus stacking.

Driven through ``manualfocusdrive`` / ``autofocusdrive``, which are deliberately not in the
settings allowlist. The lens reports no absolute position, so position is tracked relative to
an origin the user can reset. Manual drive needs live view on Nikon bodies: every move
enables the viewfinder first if it is off and restores IDLE afterwards if it had to enter live view.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from backend.api.schemas.common import EventType
from backend.camera.backend import ConfigWidget
from backend.core.camera_service import CameraService, Priority
from backend.core.clock import local_now
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraNotConnected,
    FeatureUnsupported,
    InvalidState,
    SettingInvalid,
    SettingNotFound,
)
from backend.core.jobs import HeldContext, Job, JobContext, JobManager
from backend.core.state import CameraState
from backend.core.storage_root import StorageRoot, as_root
from backend.services.capture import CaptureService, sanitize_prefix
from backend.services.storage import sanitize_name

log = logging.getLogger(__name__)

OWNER = "focus-stack"
JOB_KIND = "focus-stack"
RETURN_TIMEOUT_S = 60.0
DRIVE_WAIT_S = 30.0  # bound on waiting for an in-flight drive after a cancel
_S = CameraState
_NO_MF_DRIVE = frozenset({"AF-C", "AF-A"})
_LVAF = "liveviewaffocus"  # live view's own focus mode widget (D500)
_LVAF_SERVO = "Full-time-servo AF"  # manualfocusdrive fails -110 in this mode
_LVAF_SINGLE = "Single-servo AF"
_SIZE = re.compile(r"(\d+)x(\d+)")
_MODEL_SIZES = {"D500": (5568, 3712)}
_SAFE = re.compile(r"[^A-Za-z0-9_-]+")

Sleep = Callable[[float], Awaitable[object]]


class FocusService:
    def __init__(
        self,
        camera: CameraService,
        capture: CaptureService,
        jobs: JobManager,
        output_dir: Path | StorageRoot,
        *,
        sleep: Sleep = asyncio.sleep,
        return_timeout_s: float = RETURN_TIMEOUT_S,
        default_prefix: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._default_prefix = default_prefix
        self._camera = camera
        self._capture = capture
        self._jobs = jobs
        self._store = as_root(output_dir)
        self._sleep = sleep
        self._return_timeout = return_timeout_s
        self._lock = asyncio.Lock()
        self._pos = 0
        self._last_af_at: datetime | None = None
        self._range: tuple[int, int, int] | None = None
        self._size: tuple[tuple[Any, Any], tuple[int, int]] | None = None
        self._lva_orig: str | None = None  # live view AF mode to restore after we switched it
        self._lva_watch: asyncio.Task[None] | None = None

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

    async def _require_drivable(self) -> None:
        """Bodies with a live view AF mode widget (``liveviewaffocus``) drive in live view whatever
        ``focusmode`` says, because the drive switches that widget to single-servo while it runs.
        Others: MF drive only works in AF-S or M: in AF-C/AF-A it fails with -110 (busy) after a
        long wait, so fail early with a clear message. Unreadable mode: go on."""
        try:
            await self._camera.refresh_setting(_LVAF)
            return
        except SettingNotFound:
            pass
        except AppError:
            return
        try:
            w = await self._camera.refresh_setting("focusmode")
        except AppError:
            return
        mode = str(w.value or "").strip().upper()
        if mode in _NO_MF_DRIVE:
            raise InvalidState(
                f"Manual focus drive and focus stacking need focus mode AF-S or MF; "
                f"the camera is in {w.value}. Change the focus mode on the body.",
                details={"focusmode": w.value, "needs": ["AF-S", "MF"]},
            )

    def _lva_switch(self, b: Any) -> None:
        """Camera-thread step, live view on: Full-time-servo AF makes ``manualfocusdrive`` fail
        with -110, so switch to single-servo and remember the original for ``_restore_lva``."""
        try:
            cur = str(b.get_config(_LVAF).value)
        except SettingNotFound:
            return  # body without the widget: nothing to do
        if cur != _LVAF_SERVO:
            return
        try:
            b.set_config(_LVAF, _LVAF_SINGLE)
        except AppError as e:
            raise InvalidState(
                "Manual focus needs single-servo: set Live View AF to AF-S on the camera",
                details={"liveviewaffocus": cur},
            ) from e
        if self._lva_orig is None:
            self._lva_orig = cur

    async def _restore_lva(self, owner: str | None = None) -> None:
        orig, self._lva_orig = self._lva_orig, None
        if orig is None:
            return
        try:
            await self._camera.call(
                lambda b: b.set_config(_LVAF, orig), priority=Priority.CONTROL, owner=owner
            )
        except AppError as e:
            log.warning("could not restore live view AF mode %r: %s", orig, e)

    def _watch_liveview_end(self) -> None:
        """Single MF taps in a live view the user started would toggle the mode every time, so
        keep single-servo until live view ends (back to IDLE), then restore. A lost connection
        just forgets it (the camera resets itself)."""
        if self._lva_watch is not None and not self._lva_watch.done():
            return
        sub = self._camera.bus.subscribe()

        async def watch() -> None:
            async with sub:
                async for ev in sub:
                    if ev.type == EventType.CAMERA_DISCONNECTED:
                        self._lva_orig = None
                        return
                    if ev.type == EventType.CAMERA_STATE and ev.data.get("state") == "idle":
                        break
            await self._restore_lva()

        self._lva_watch = asyncio.create_task(watch(), name="focus-lva-restore")

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

    async def _full_size(self) -> tuple[int, int]:
        """Full-sensor pixel size ``changeafarea`` is expressed in: the largest ``imagesize``
        choice, else a per-model table, else the live view preview size. Cached per connection."""
        st = self._camera.status()
        key = (st.model, st.connected_at)
        if self._size is not None and self._size[0] == key:
            return self._size[1]
        size: tuple[int, int] | None = None
        try:
            w: ConfigWidget = await self._camera.call(
                lambda b: b.get_config("imagesize"), priority=Priority.CONTROL
            )
            dims = [(int(m[1]), int(m[2])) for c in w.choices if (m := _SIZE.fullmatch(c.strip()))]
            size = max(dims, key=lambda d: d[0] * d[1]) if dims else None
        except AppError:
            pass
        if size is None:
            model = (st.model or "").upper()
            size = next((v for k, v in _MODEL_SIZES.items() if k in model), None)
        cacheable = True  # false for the preview fallback: it can follow a transient failure
        if size is None:
            cacheable = False
            with Image.open(io.BytesIO(await self._camera.preview_frame())) as im:
                size = im.size
        if cacheable:
            self._size = (key, size)
        return size

    async def set_af_point(self, x: float, y: float) -> tuple[int, int]:
        """Move the AF point to normalized (x, y) via ``changeafarea`` (text "XxY" in
        full-sensor pixels; the camera clamps to keep the AF box inside). Needs live view.
        Returns the pixel point sent."""
        self._require_free(None)
        if self._camera.state != _S.LIVEVIEW:
            raise InvalidState("Live view must be on to move the AF point")
        w, h = await self._full_size()
        px, py = min(w - 1, int(x * w)), min(h - 1, int(y * h))
        async with self._lock:
            try:
                await self._camera.call(
                    lambda b: b.set_config("changeafarea", f"{px}x{py}"),
                    priority=Priority.CONTROL,
                )
            except SettingNotFound:
                raise FeatureUnsupported("This camera cannot move the AF point") from None
        return px, py

    async def move(self, steps: int, *, owner: str | None = None) -> int:
        """Drive focus by ``steps`` (signed); returns the new relative position."""
        lo, hi, step = await self.get_range()
        if steps == 0 or not lo <= steps <= hi or (steps - lo) % step:
            raise SettingInvalid(
                f"steps must be non-zero and within [{lo}, {hi}]",
                details={"steps": steps, "min": lo, "max": hi, "step": step},
            )
        self._require_free(owner)
        if owner is None:  # a running stack checked this once up front
            await self._require_drivable()
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
                    self._lva_switch(b)
                    b.set_config("manualfocusdrive", steps)

                await self._drive_tracked(_drive, steps, owner)
            finally:
                if owner is None:  # a running stack restores at its end
                    if entered:
                        await self._restore_lva()
                    elif self._lva_orig is not None:
                        self._watch_liveview_end()
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
        filename_prefix: str | None = None,
    ) -> Job:
        prefix = sanitize_prefix(filename_prefix or self._default_prefix())
        self._require_free(None)
        self._store.root()  # NoTargetError (409) before any camera work
        sign = 1 if direction == "near_to_far" else -1
        delta = sign * steps_per_shot
        await self._require_drivable()
        lo, hi, step = await self.get_range()
        if not lo <= delta <= hi or (delta - lo) % step:
            raise SettingInvalid(
                f"steps_per_shot must move focus within [{lo}, {hi}] in steps of {step}",
                details={"steps": delta, "min": lo, "max": hi, "step": step},
            )

        async def factory(ctx: JobContext) -> dict[str, Any]:
            try:
                return await self._run_stack(
                    ctx, delta, shots, settle_ms / 1000, return_to_start, name, prefix
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
        stamp = local_now().strftime("%Y-%m-%d-%H%M%S")
        label = sanitize_name(_SAFE.sub("-", name or ""), default="").strip("_-")
        base = self._store.root() / "stacks"
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
        prefix: str = "",
    ) -> dict[str, Any]:
        prior = self._camera.state
        start_pos = self._pos
        dest = await asyncio.to_thread(self._make_dest, name)
        folder = dest.relative_to(self._store.root()).as_posix()
        files = moves = 0
        try:
            for i in range(shots):
                if ctx.cancelled:
                    break
                ctx.report(i / shots, f"Shot {i + 1}/{shots}")
                paths = await self._capture.capture_to(
                    dest, owner=OWNER, name_prefix=f"{prefix}{i + 1:03d}-"
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
                await self._restore_lva(OWNER)
                state = self._camera.state
                if prior == _S.LIVEVIEW and state == _S.IDLE:
                    await self._camera.transition(_S.LIVEVIEW)
                elif prior == _S.IDLE and state == _S.LIVEVIEW:
                    await self._camera.transition(_S.IDLE)
        except (AppError, TimeoutError) as e:
            log.warning("focus stack cleanup incomplete: %s", e)
        finally:
            if self._lva_orig is not None:  # the return moves failed or timed out
                await self._restore_lva(OWNER)
