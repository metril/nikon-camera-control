"""Live view: ONE producer task for the whole app, fanned out to 1-slot mailboxes.

- The producer loops ``CameraService.preview_frame()`` at ``liveview.target_fps`` (read live
  each iteration) and hands each frame to every subscriber's mailbox. A mailbox holds only the
  latest frame (drop-old), so a slow client skips frames and never delays others.
- Reference counted: the producer starts on the first subscriber or an explicit (sticky)
  ``start()``, moves the camera IDLE -> LIVEVIEW through ``CameraService.transition`` and
  moves it back to IDLE when the last subscriber leaves (and it is not sticky) or on ``stop()``;
  ``CameraService.transition(IDLE)`` out of LIVEVIEW also switches the camera's viewfinder off.
- Camera state is polled/awaited every iteration, never cached: the producer pauses (keeping
  subscribers) while the camera is CAPTURING/BULB/BUSY/ERROR or disconnected, and
  resumes by itself. ``preview_frame`` works in LIVEVIEW and RECORDING (the D500 keeps
  streaming previews while recording a movie), so the stream continues during a recording.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from backend.api.schemas.common import EventType
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import AppError, CameraNotConnected, InvalidState
from backend.core.events import EventBus
from backend.core.state import CameraState

log = logging.getLogger(__name__)

_S = CameraState
_POLL_S = 0.05
_ERROR_BACKOFF_S = 0.2
_CRASH_RESTART_S = 2.0  # delay before restarting a producer that crashed
_MAX_WIDTH = {"small": 640, "medium": 1024, "large": None}
_FPS_WINDOW = 30

Phase = Literal["stopped", "waiting", "streaming"]


@dataclass(frozen=True, slots=True)
class LiveViewStats:
    running: bool
    active: bool
    sticky: bool
    phase: Phase
    reason: str | None
    camera_state: CameraState
    fps: float
    target_fps: int
    subscribers: int
    frames_produced: int
    frames_sent: int
    frames_dropped: int
    last_frame_bytes: int | None
    last_frame_at: float | None  # unix seconds


class Subscriber:
    """Latest-frame mailbox plus a pending-status flag; ``get`` returns one item at a time."""

    def __init__(self) -> None:
        self._frame: bytes | None = None
        self._status = True  # a status message is owed on connect
        self._event = asyncio.Event()
        self.closed = False
        self.frames_sent = 0
        self.frames_dropped = 0
        self._event.set()

    def _offer_frame(self, frame: bytes) -> None:
        if self.closed:
            return
        if self._frame is not None:
            self.frames_dropped += 1  # slot still unread: drop-old
        self._frame = frame
        self._event.set()

    def _offer_status(self) -> None:
        if not self.closed:
            self._status = True
            self._event.set()

    def _close(self) -> None:
        self.closed = True
        self._frame = None
        self._event.set()

    async def get(self) -> tuple[Literal["status", "frame"], bytes | None] | None:
        """Next item, status first; None once closed."""
        while True:
            if self.closed:
                return None
            if self._status:
                self._status = False
                return "status", None
            if self._frame is not None:
                frame, self._frame = self._frame, None
                self.frames_sent += 1
                return "frame", frame
            self._event.clear()
            await self._event.wait()


def process_frame(frame: bytes, max_width: int | None, jpeg_quality: int) -> bytes:
    """Downscale/recompress only if wider than ``max_width``; else return ``frame`` as is."""
    if max_width is None:
        return frame
    try:
        with Image.open(io.BytesIO(frame)) as img:
            if img.width <= max_width:
                return frame
            h = max(1, round(img.height * max_width / img.width))
            out = io.BytesIO()
            img.convert("RGB").resize((max_width, h)).save(out, "JPEG", quality=jpeg_quality)
            return out.getvalue()
    except Exception:
        log.debug("live view frame not processable; passing through", exc_info=True)
        return frame


class LiveViewService:
    def __init__(
        self,
        camera: CameraService,
        bus: EventBus,
        config: ConfigStore,
        *,
        interval_s: float | None = None,
    ) -> None:
        """``interval_s`` overrides the config's target_fps interval (tests)."""
        self._camera = camera
        self._bus = bus
        self._config = config
        self._interval_override = interval_s
        self._subs: set[Subscriber] = set()
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._sticky = False
        self._closed = False
        self._phase: Phase = "stopped"
        self._reason: str | None = None
        self._times: deque[float] = deque(maxlen=_FPS_WINDOW)
        self._produced = 0
        self._sent_closed = 0  # sent/dropped of departed subscribers
        self._dropped_closed = 0
        self._last_bytes: int | None = None
        self._last_at: float | None = None
        self._snap_lock = asyncio.Lock()
        self._announced = False

    # public API -------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def subscribe(self) -> Subscriber:
        sub = Subscriber()
        if self._closed:
            sub._close()
            return sub
        self._subs.add(sub)
        self._ensure_producer()
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        """Synchronous and idempotent; the producer notices and releases the camera."""
        if sub in self._subs:
            self._subs.discard(sub)
            self._sent_closed += sub.frames_sent
            self._dropped_closed += sub.frames_dropped
        sub._close()
        self._wake.set()

    async def start(self) -> None:
        """Explicit start: stays running until ``stop()`` even with no subscribers."""
        if self._closed:
            return
        self._sticky = True
        self._ensure_producer()
        self._notify()

    async def stop(self) -> None:
        """Explicit stop: producer ends, camera returns to IDLE; subscribers stay, told so."""
        self._sticky = False
        await self._stop_producer()
        self._notify()

    async def aclose(self) -> None:
        self._closed = True
        self._sticky = False
        await self._stop_producer()
        for sub in list(self._subs):
            self.unsubscribe(sub)

    def stats(self) -> LiveViewStats:
        cam = self._camera.state
        sent = self._sent_closed + sum(s.frames_sent for s in self._subs)
        dropped = self._dropped_closed + sum(s.frames_dropped for s in self._subs)
        return LiveViewStats(
            running=self.running,
            active=self.running and self._phase == "streaming",
            sticky=self._sticky,
            phase=self._phase,
            reason=self._reason,
            camera_state=cam,
            fps=self._fps(),
            target_fps=self._config.config.liveview.target_fps,
            subscribers=len(self._subs),
            frames_produced=self._produced,
            frames_sent=sent,
            frames_dropped=dropped,
            last_frame_bytes=self._last_bytes,
            last_frame_at=self._last_at,
        )

    async def snapshot(self) -> bytes:
        """One JPEG, whether or not the stream runs; restores the prior camera state."""
        st = self._camera.state
        if st in (_S.DISCONNECTED, _S.CONNECTING):
            raise CameraNotConnected()
        if st in (_S.LIVEVIEW, _S.RECORDING):
            return await self._processed(await self._camera.preview_frame())
        async with self._snap_lock:
            prior = await self._camera.transition(_S.LIVEVIEW)  # InvalidState if not allowed
            try:
                frame = await self._preview_retry()
            finally:
                # keep LIVEVIEW if the stream was started meanwhile
                if not self.running and self._camera.state == _S.LIVEVIEW:
                    with contextlib.suppress(AppError):
                        await self._camera.transition(prior)
            return await self._processed(frame)

    # producer ---------------------------------------------------------------------------
    def _ensure_producer(self) -> None:
        if not self.running:
            self._wake.clear()
            self._task = asyncio.create_task(self._run(), name="liveview-producer")
            self._announced = True
            self._bus.publish(EventType.LIVEVIEW_STARTED, {})
        self._wake.set()

    async def _stop_producer(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._set_phase("stopped", None)
        self._announce_stopped()
        await self._release()

    def _demand(self) -> bool:
        return bool(self._subs) or self._sticky

    async def _run(self) -> None:
        crashed = False
        try:
            await self._loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live view producer crashed")
            crashed = True
        else:
            await self._release()
        finally:
            ended = self._task is asyncio.current_task()
            if ended:
                self._task = None
            self._set_phase("stopped", None)
            self._announce_stopped()
            if ended and not self._closed and self._demand():
                if crashed:  # back off: never a tight crash/restart loop
                    asyncio.get_running_loop().call_later(_CRASH_RESTART_S, self._restart_if_wanted)
                else:
                    self._ensure_producer()  # someone subscribed while we were releasing the camera

    def _restart_if_wanted(self) -> None:
        if not self._closed and self._demand() and not self.running:
            self._ensure_producer()

    def _announce_stopped(self) -> None:
        if self._announced:
            self._announced = False
            self._bus.publish(EventType.LIVEVIEW_STOPPED, {"frames": self._produced})

    async def _release(self) -> None:
        """LIVEVIEW -> IDLE if we own it; never raises."""
        if self._camera.state == _S.LIVEVIEW:
            with contextlib.suppress(AppError):
                await self._camera.transition(_S.IDLE)

    async def _loop(self) -> None:
        errors = 0
        while self._demand():
            t0 = time.monotonic()
            cam = self._camera.state
            if cam in (_S.DISCONNECTED, _S.CONNECTING):
                self._set_phase("waiting", "camera_disconnected")
                await self._sleep(_POLL_S)
                continue
            if cam == _S.IDLE:
                try:
                    await self._camera.transition(_S.LIVEVIEW)
                except InvalidState:
                    continue
                cam = _S.LIVEVIEW
            if cam not in (_S.LIVEVIEW, _S.RECORDING):
                self._set_phase("waiting", f"camera_{cam.value}")
                await self._sleep(_POLL_S)
                continue
            try:
                frame = await self._camera.preview_frame()
            except CameraNotConnected:
                self._set_phase("waiting", "camera_disconnected")
                await self._sleep(_POLL_S)
                continue
            except InvalidState:
                await self._sleep(_POLL_S)  # state changed under us; re-evaluate
                continue
            except AppError as e:
                errors += 1
                self._set_phase("waiting", "preview_failed")
                log.debug("live view preview failed (%d): %s", errors, e)
                await self._sleep(_ERROR_BACKOFF_S)
                continue
            errors = 0
            frame = await self._processed(frame)
            self._publish_frame(frame)
            self._set_phase("streaming", None)
            await self._sleep(max(0.0, self._interval() - (time.monotonic() - t0)))

    def _publish_frame(self, frame: bytes) -> None:
        now = time.monotonic()
        self._times.append(now)
        self._produced += 1
        self._last_bytes = len(frame)
        self._last_at = time.time()
        for sub in self._subs:
            sub._offer_frame(frame)

    def _interval(self) -> float:
        if self._interval_override is not None:
            return self._interval_override
        return 1.0 / max(1, self._config.config.liveview.target_fps)

    def _fps(self) -> float:
        t = self._times
        if len(t) < 2 or time.monotonic() - t[-1] > 2.0:
            return 0.0
        span = t[-1] - t[0]
        return round((len(t) - 1) / span, 2) if span > 0 else 0.0

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    def _set_phase(self, phase: Phase, reason: str | None) -> None:
        if (phase, reason) != (self._phase, self._reason):
            self._phase, self._reason = phase, reason
            self._notify()

    def _notify(self) -> None:
        for sub in self._subs:
            sub._offer_status()

    async def _processed(self, frame: bytes) -> bytes:
        cfg = self._config.config.liveview
        width = _MAX_WIDTH[cfg.quality]
        if width is None:
            return frame
        return await asyncio.to_thread(process_frame, frame, width, cfg.jpeg_quality)

    async def _preview_retry(self) -> bytes:
        for _ in range(4):
            with contextlib.suppress(AppError):
                return await self._camera.preview_frame()
            await asyncio.sleep(0.05)
        return await self._camera.preview_frame()
