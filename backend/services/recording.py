"""In-camera video recording (``movie`` widget) on top of CameraService.

Flow: start takes ``camera.lease("recording")`` for the whole recording, makes sure live view
is on (remembering whether it already was), moves the camera to RECORDING and sets
``movie``=1. A watchdog task stops it at the time limit and notices a camera that stopped by
itself or went away. If the camera was reset (timeout -> ERROR -> IDLE) mid-recording the
watchdog waits for it to be usable again and still sends the real stop; only a real
disconnect ends the session without a stop command. Stop sets ``movie``=0 (retried), waits a
bounded time for the FILE_ADDED event of the clip, restores the prior state and releases the
lease.

Camera access only through ``CameraService.call(..., owner="recording")``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.api.schemas.common import EventType
from backend.camera.backend import CameraBackend, CameraFileInfo, CameraFilePath
from backend.camera.backend import EventType as CamEventType
from backend.core.camera_service import CameraService
from backend.core.errors import (
    AppError,
    CameraNotConnected,
    CameraOperationFailed,
    InvalidState,
    SettingNotFound,
    StorageFull,
)
from backend.core.events import EventBus
from backend.core.jobs import Job, JobContext, JobManager
from backend.core.state import CameraState
from backend.core.storage_root import StorageRoot, as_root
from backend.services.storage import classify, download_files

log = logging.getLogger(__name__)

_S = CameraState
OWNER = "recording"
MAX_CLIP_S = 1799  # D500: 29 min 59 s per clip
STOP_WINDOW_S = 15.0  # keep retrying a refused stop for this long (D500 refuses right after start)
FILE_WAIT_ATTEMPTS = 20  # x _EVENT_WAIT_S = bounded wait for the clip's FILE_ADDED
_EVENT_WAIT_S = 0.25
_POLL_S = 1.0
RECOVER_POLLS = 30  # bounded wait for a reset camera to become usable again
START_UNDO_S = 10.0  # bound for the best-effort movie=0 after a failed start
_RETRY_DELAY_S = 0.5
_OFF_VALUES = frozenset({"", "0", "false", "off", "none"})
RECORDINGS_DIR = "recordings"


def _is_on(value: object) -> bool:
    return str(value).strip().lower() not in _OFF_VALUES


def _wrong_target(value: object) -> bool:
    v = str(value).lower()
    return "ram" in v or "sdram" in v


_TARGET_WARNING = (
    "Capture target is {value!r}; D500? Nikon movie recording normally goes to the memory "
    "card regardless, but check the card if no clip appears."
)


@dataclass(slots=True)
class _Active:
    started_at: datetime
    t0: float
    max_seconds: int
    download_after: bool
    was_liveview: bool
    stack: AsyncExitStack
    clips: list[CameraFilePath] = field(default_factory=list)
    stopped_at: float | None = None


@dataclass(slots=True)
class _Last:
    started_at: datetime | None = None
    elapsed_s: float = 0.0
    max_seconds: int | None = None
    clips: list[tuple[CameraFilePath, int]] = field(default_factory=list)
    job_id: str | None = None
    reason: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class RecordingInfo:
    active: bool
    started: datetime | None
    elapsed_s: float
    max_seconds: int | None
    state: CameraState
    last_clip: tuple[CameraFilePath, int] | None
    job_id: str | None
    reason: str | None
    warning: str | None
    segments: int = 0
    note: str | None = None


def _drain(b: CameraBackend, wait_s: float) -> list[CameraFilePath]:
    """New movie files from the camera event queue (worker thread)."""
    out: list[CameraFilePath] = []
    first = True
    while True:
        ev = b.wait_for_event(wait_s if first else 0.0)
        first = False
        if ev.type == CamEventType.TIMEOUT:
            return out
        if ev.type == CamEventType.FILE_ADDED and ev.file and classify(ev.file.name) == "video":
            out.append(ev.file)


def _lister(folder: str) -> Callable[[CameraBackend], list[CameraFileInfo]]:
    return lambda b: b.list_files(folder)


class RecordingService:
    def __init__(
        self,
        camera: CameraService,
        bus: EventBus,
        jobs: JobManager,
        output_dir: Path | StorageRoot,
        *,
        liveview_running: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        poll_s: float = _POLL_S,
        retry_delay_s: float = _RETRY_DELAY_S,
    ) -> None:
        """``clock``/``sleep``/``poll_s`` are injectable so the watchdog runs on virtual time
        in tests. ``liveview_running``: True if the live view service wants the stream."""
        self._camera = camera
        self._bus = bus
        self._jobs = jobs
        self._store = as_root(output_dir)
        self._lv_running = liveview_running
        self._clock = clock
        self._sleep = sleep
        self._poll_s = poll_s
        self._retry_delay_s = retry_delay_s
        self._lock = asyncio.Lock()
        self._active: _Active | None = None
        self._last = _Last()
        self._watchdog: asyncio.Task[None] | None = None
        self._closed = False

    # public API -------------------------------------------------------------------------
    def info(self) -> RecordingInfo:
        a, last = self._active, self._last
        if a is not None:
            return RecordingInfo(
                True,
                a.started_at,
                max(0.0, self._clock() - a.t0),
                a.max_seconds,
                self._camera.state,
                last.clips[-1] if last.clips else None,
                None,
                last.reason,
                last.warning,
                len(a.clips),
                self._note(max(0.0, self._clock() - a.t0)),
            )
        return RecordingInfo(
            False,
            last.started_at,
            last.elapsed_s,
            last.max_seconds,
            self._camera.state,
            last.clips[-1] if last.clips else None,
            last.job_id,
            last.reason,
            last.warning,
            len(last.clips),
            self._note(last.elapsed_s),
        )

    @staticmethod
    def _note(elapsed_s: float) -> str | None:
        if elapsed_s >= MAX_CLIP_S:
            return "Past the camera's 29:59 clip limit: the camera has probably stopped by itself"
        return None

    async def start(self, *, max_seconds: int | None, download_after: bool) -> RecordingInfo:
        async with self._lock:
            if self._closed:
                raise InvalidState("Recording service is shutting down")
            if self._active is not None:
                raise InvalidState("A recording is already in progress")
            if download_after:
                self._store.root()  # NoTargetError (409) before recording starts
            st = self._camera.state
            if st in (_S.DISCONNECTED, _S.CONNECTING):
                raise CameraNotConnected()
            if st not in (_S.IDLE, _S.LIVEVIEW):
                raise InvalidState(
                    f"Cannot start recording while the camera is {st.value}",
                    details={"state": st.value},
                )
            limit = min(max_seconds or MAX_CLIP_S, MAX_CLIP_S)
            stack = AsyncExitStack()
            await stack.enter_async_context(self._camera.lease(OWNER))  # CameraBusy if taken
            restore: CameraState | None = None
            issued: asyncio.Future[None] | None = None
            warning: str | None = None
            try:
                warning = await self._check_capture_target()
                was_lv = st == _S.LIVEVIEW
                if not was_lv:
                    await self._camera.transition(_S.LIVEVIEW)
                    restore = _S.IDLE
                await self._camera.preview_frame()  # switches the viewfinder on if needed
                await self._camera.transition(_S.RECORDING)
                restore = _S.LIVEVIEW if was_lv else _S.IDLE
                # Shielded: a cancelled request must not leave a queued movie=1 untracked.
                issued = asyncio.ensure_future(
                    self._camera.call(lambda b: b.set_config("movie", 1), owner=OWNER)
                )
                try:
                    await asyncio.shield(issued)
                except (CameraNotConnected, InvalidState):
                    raise
                except AppError as e:
                    raise CameraOperationFailed(
                        f"The camera refused to start recording ({e.message}). On Nikon bodies "
                        "the live view selector must be set to movie mode.",
                        details={"cause": e.message},
                    ) from e
            except BaseException:
                if issued is not None:
                    await self._undo_start(issued)
                await self._rollback(restore, was_lv=st == _S.LIVEVIEW)
                await stack.aclose()
                raise
            self._active = _Active(
                datetime.now(UTC), self._clock(), limit, download_after, st == _S.LIVEVIEW, stack
            )
            self._last = _Last(
                started_at=self._active.started_at, max_seconds=limit, warning=warning
            )
            self._bus.publish(
                EventType.RECORDING_STARTED,
                {"max_seconds": limit, "download_after": download_after},
            )
            self._watchdog = asyncio.create_task(self._watch(), name="recording-watchdog")
            return self.info()

    async def stop(self) -> RecordingInfo:
        # Runs as its own task so a cancelled request cannot abort the stop half way.
        task = asyncio.ensure_future(self._stop_locked())
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        return await asyncio.shield(task)

    async def _stop_locked(self) -> RecordingInfo:
        async with self._lock:
            if self._active is None:
                raise InvalidState("No recording is in progress")
            wd, self._watchdog = self._watchdog, None
            if wd is not None and wd is not asyncio.current_task():
                wd.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await wd
            try:
                await self._finish("user")
            except BaseException:
                self._watchdog = asyncio.create_task(self._watch(), name="recording-watchdog")
                raise
            return self.info()

    async def aclose(self) -> None:
        """Shutdown: stop an active recording (never raises)."""
        self._closed = True
        wd, self._watchdog = self._watchdog, None
        if wd is not None:
            wd.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await wd
        async with self._lock:
            if self._active is None:
                return
            try:
                await self._finish("shutdown")
            except Exception:
                log.critical("COULD NOT STOP RECORDING AT SHUTDOWN; camera may still be recording")
                a, self._active = self._active, None
                await a.stack.aclose()

    # internals --------------------------------------------------------------------------
    async def _check_capture_target(self) -> str | None:
        """Non-blocking: libgphoto2 defaults to Internal RAM and the body records to the card
        anyway, so a RAM target only yields a warning."""
        try:
            w = await self._camera.call(lambda b: b.get_config("capturetarget"), owner=OWNER)
        except SettingNotFound:
            return None  # body without the widget: assume the card
        return _TARGET_WARNING.format(value=str(w.value)) if _wrong_target(w.value) else None

    async def _undo_start(self, issued: asyncio.Future[None]) -> None:
        """movie=1 was sent but the start failed: make sure the camera is not left recording."""
        await asyncio.wait({issued}, timeout=START_UNDO_S)  # never cancels it
        if issued.done() and not issued.cancelled():
            exc = issued.exception()
            if isinstance(exc, CameraNotConnected):
                return
        try:
            await asyncio.wait_for(
                asyncio.shield(
                    self._camera.call(
                        lambda b: b.set_config("movie", 0), owner=OWNER, timeout=START_UNDO_S
                    )
                ),
                START_UNDO_S + 1,
            )
        except (AppError, TimeoutError):
            log.warning("could not undo a failed recording start; camera may be recording")

    async def _rollback(self, restore: CameraState | None, *, was_lv: bool) -> None:
        """Undo a failed start (best effort)."""
        with contextlib.suppress(AppError):
            if self._camera.state == _S.RECORDING:
                await self._camera.transition(_S.LIVEVIEW)
        if restore == _S.IDLE or (restore is None and not was_lv):
            with contextlib.suppress(AppError):
                if self._camera.state == _S.LIVEVIEW:
                    await self._camera.transition(_S.IDLE)

    async def _watch(self) -> None:
        try:
            while (a := self._active) is not None:
                await self._sleep(self._poll_s)
                if self._active is not a:
                    return
                if (st := self._camera.state) != _S.RECORDING:
                    if st in (_S.DISCONNECTED, _S.CONNECTING):
                        await self._ended_without_us(a)
                    else:
                        await self._recover(a)
                    return
                if self._clock() - a.t0 >= a.max_seconds:
                    await self._auto("max_seconds")
                    return
                try:
                    new = await self._camera.call(lambda b: _drain(b, 0.0), owner=OWNER)
                except CameraNotConnected:
                    continue  # state check above handles it on the next round
                except StorageFull:
                    await self._auto("camera_stopped")  # explicit error from the camera
                    return
                except AppError:
                    log.debug("recording poll failed", exc_info=True)
                    continue
                # A movie FILE_ADDED mid-recording is only a segment (the body splits files
                # and keeps recording); it never means the camera stopped.
                a.clips.extend(f for f in new if f not in a.clips)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("recording watchdog crashed")

    async def _recover(self, a: _Active) -> None:
        """Camera left RECORDING but is still connected (timeout -> ERROR -> reset -> IDLE):
        it may still be recording, so wait (bounded) until it is usable and send the stop."""
        for _ in range(RECOVER_POLLS):
            st = self._camera.state
            if st in (_S.DISCONNECTED, _S.CONNECTING):
                await self._ended_without_us(a)
                return
            if st != _S.ERROR:
                break
            await self._sleep(self._poll_s)
            if self._active is not a:
                return
        await self._auto("camera_reset", retry=False)

    async def _auto(self, reason: str, *, retry: bool = True) -> None:
        async with self._lock:
            if self._active is None:
                return
            self._watchdog = None
            try:
                await self._finish(reason)
            except Exception as e:
                log.critical("AUTOMATIC STOP OF THE RECORDING FAILED (%s)", reason)
                if self._active is not None:
                    msg = e.message if isinstance(e, AppError) else str(e)
                    self._last.reason = reason
                    self._last.warning = (
                        f"Automatic stop failed ({msg}); the camera may still be recording. "
                        "Retry POST /recording/stop."
                    )
                    if retry:
                        self._watchdog = asyncio.create_task(
                            self._watch(), name="recording-watchdog"
                        )

    async def _ended_without_us(self, a: _Active) -> None:
        """Camera disconnected: clean up what we own (no stop command can be sent)."""
        async with self._lock:
            if self._active is not a:
                return
            self._watchdog = None
            reason = "camera_disconnected"
            warning = (
                "Camera disconnected during recording; the clip may be incomplete, and if it "
                "was only a USB drop the camera may still be recording"
            )
            self._record_end(a, reason, warning)
            self._active = None
            await a.stack.aclose()
            self._bus.publish(
                EventType.RECORDING_STOPPED,
                {"reason": reason, "duration_s": self._last.elapsed_s, "warning": warning,
                 "clips": [], "job_id": None},
            )  # fmt: skip
            log.warning("recording ended: %s", warning)

    def _record_end(self, a: _Active, reason: str, warning: str | None) -> None:
        self._last.elapsed_s = max(0.0, (a.stopped_at or self._clock()) - a.t0)
        self._last.reason = reason
        self._last.warning = warning

    async def _stop_camera(self, a: _Active) -> None:
        """Send movie=0, retrying with backoff for STOP_WINDOW_S. On success records the real
        stop time (``a.stopped_at``) so the reported duration is not inflated by retries."""
        err: AppError | None = None
        attempts = max(1, round(STOP_WINDOW_S / self._retry_delay_s)) if self._retry_delay_s else 30
        for attempt in range(attempts):
            try:
                await self._camera.call(lambda b: b.set_config("movie", 0), owner=OWNER)
                a.stopped_at = self._clock()
                if attempt:
                    log.warning("recording stopped after %d attempts", attempt + 1)
                return
            except AppError as e:
                err = e
                log.error("stop recording failed (attempt %d): %s", attempt + 1, e.message)
                if isinstance(e, CameraNotConnected):
                    raise
                await asyncio.sleep(self._retry_delay_s)
        cause = err.message if err else "unknown"
        raise CameraOperationFailed(
            f"FAILED TO STOP RECORDING after {attempts} attempts ({cause}); the camera "
            "may still be recording. Retry POST /recording/stop or stop it on the body.",
            details={"cause": cause},
        )

    async def _finish(self, reason: str) -> None:
        """Stop the camera, wait for the clip, restore state, release the lease, announce.
        Caller holds the lock. Raises (keeping the recording active) if the stop failed."""
        a = self._active
        if a is None:
            raise InvalidState("No recording is in progress")
        warning: str | None = None
        try:
            await self._stop_camera(a)
        except CameraNotConnected:
            warning = "Camera disconnected while stopping; the clip may be incomplete"
        attempts = 1 if reason == "camera_stopped" else FILE_WAIT_ATTEMPTS
        for _ in range(attempts if warning is None else 0):
            try:
                got = await self._camera.call(lambda b: _drain(b, _EVENT_WAIT_S), owner=OWNER)
            except AppError:
                break
            a.clips.extend(f for f in got if f not in a.clips)
            if got and a.clips:
                break
        if warning is None and not a.clips:
            warning = "No clip file event received; find the movie on the card"
        self._record_end(a, reason, warning)
        sized: list[tuple[CameraFilePath, int]] = []
        job_id: str | None = None
        try:
            await self._restore(a)
            sized = await self._sizes(a.clips)
            self._last.clips = sized
            if a.download_after and sized:
                try:
                    job_id = self._submit_download([c for c, _ in sized]).id
                except AppError as e:
                    warning = (
                        f"{warning + '; ' if warning else ''}download not started: {e.message}"
                    )
                    self._last.warning = warning
            self._last.job_id = job_id
        finally:
            await a.stack.aclose()
            self._active = None
        self._bus.publish(
            EventType.RECORDING_STOPPED,
            {
                "reason": reason,
                "duration_s": self._last.elapsed_s,
                "warning": warning,
                "clips": [{"folder": c.folder, "name": c.name, "size": n} for c, n in sized[:20]],
                "job_id": job_id,
            },
        )

    async def _restore(self, a: _Active) -> None:
        cam = self._camera
        with contextlib.suppress(AppError):
            if cam.state == _S.RECORDING:
                await cam.transition(_S.LIVEVIEW)
        if not a.was_liveview and not self._lv_running():
            with contextlib.suppress(AppError):
                if cam.state == _S.LIVEVIEW:
                    await cam.transition(_S.IDLE)  # also switches the viewfinder off

    async def _sizes(self, clips: list[CameraFilePath]) -> list[tuple[CameraFilePath, int]]:
        out: list[tuple[CameraFilePath, int]] = []
        for c in clips:
            size = 0
            try:
                infos = await self._camera.call(_lister(c.folder), owner=OWNER)
                size = next((i.size for i in infos if i.name == c.name), 0)
            except AppError:
                log.debug("could not size %s", c.name, exc_info=True)
            out.append((c, size))
        return out

    def _submit_download(self, clips: list[CameraFilePath]) -> Job:
        camera = self._camera
        store = self._store

        async def run(ctx: JobContext) -> dict[str, object]:
            root = store.root()
            for _clip, size in await self._sizes(clips):
                store.check_file_size(size)  # FAT32 4 GiB limit
            ctx.report(0.0, "Downloading recording")
            paths = await download_files(
                camera, clips, root / RECORDINGS_DIR, on_stored=store.stored
            )
            ctx.report(1.0, "Done")
            return {"files": [p.relative_to(root).as_posix() for p in paths]}

        return self._jobs.submit("recording_download", run)
