"""CameraService: the single owner of the camera, its state machine and its worker thread.

Design contract
---------------
- One worker thread runs every blocking ``CameraBackend`` call, fed by a
  ``queue.PriorityQueue``. Priority order (lower runs first): CONTROL < CAPTURE <
  KEEPALIVE < PREVIEW; FIFO within a priority. Async callers await a future resolved
  with ``loop.call_soon_threadsafe``.
- ``call(fn, priority=, timeout=)`` is the one generic way to run a backend op. If the
  op does not finish within ``timeout`` the awaiting caller gets ``CameraTimeout``, the
  service moves to ERROR, and the backend is reset (close + reopen on a fresh worker
  thread; the stuck thread is abandoned, never joined). Queued items are failed with
  CameraNotConnected/CameraTimeout; no thread pile-up.
- Every state change goes through ``transition`` (validated with
  ``core.state.can_transition``), is published on the bus as CAMERA_STATE
  ({state, previous}), plus CAMERA_CONNECTED / CAMERA_DISCONNECTED where relevant.
  Invalid transitions raise InvalidState; nothing mutates state around ``transition``.
- Keepalive: a periodic backend.summary() at KEEPALIVE priority every
  ``camera.keepalive_interval_s`` (read live from the config store). It is skipped
  while state is LIVEVIEW (preview frames keep the link alive) or a lease is held by a
  long operation that touches the camera frequently. A keepalive failure moves to
  DISCONNECTED and starts a reconnect loop (``camera.connect_retries`` attempts with
  backoff) that ends in IDLE on success or stays DISCONNECTED.
- ``disconnect()`` never joins a thread while holding a lock: it flips state first,
  signals the worker to stop, closes the backend from the worker, and waits for the
  thread outside any lock with a bounded timeout (abandoning it if stuck).
- Config cache: ``list_settings``/``get_setting`` are served from a per-connection
  cache; ``set_setting`` invalidates the affected entry (re-reads the widget) and
  publishes SETTING_CHANGED. The cache is cleared on disconnect/reconnect.
- ``lease(owner)`` is an async context manager granting exclusive use for long
  operations (time-lapse, bulb, focus stack, recording). While held, ``call`` from
  non-lessees raises CameraBusy; the lessee passes ``lease=...`` via ``call(...,
  owner=owner)``. Nested/concurrent lease raises CameraBusy.
- ``preview_frame`` is coalesced: at most one PREVIEW item is pending; concurrent
  callers share the same result.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TypeVar

from backend.camera.backend import (
    CameraBackend,
    CameraFilePath,
    ConfigWidget,
)
from backend.core.config_store import ConfigStore
from backend.core.events import EventBus
from backend.core.state import CameraState

T = TypeVar("T")


class Priority(enum.IntEnum):
    """Lower value runs first."""

    CONTROL = 0
    CAPTURE = 1
    KEEPALIVE = 2
    PREVIEW = 3


@dataclass(frozen=True, slots=True)
class CameraStatus:
    state: CameraState
    connected: bool
    model: str | None
    leased_by: str | None
    last_error: str | None
    connected_at: float | None  # unix seconds


class Lease:
    """Handle yielded by ``CameraService.lease``."""

    owner: str


class CameraService:
    def __init__(
        self,
        backend_factory: Callable[[], CameraBackend],
        config_store: ConfigStore,
        event_bus: EventBus,
    ) -> None:
        """``backend_factory`` is called on each (re)connect to get a fresh backend
        (real gphoto2 or FakeCamera). It is invoked on the worker thread."""
        raise NotImplementedError

    # lifecycle ---------------------------------------------------------------
    async def start(self) -> None:
        """Bind the bus to the running loop and start the worker thread + keepalive task.
        Does not connect. Idempotent."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Disconnect, stop keepalive/reconnect tasks, stop the worker (bounded wait)."""
        raise NotImplementedError

    async def connect(self) -> CameraStatus:
        """DISCONNECTED/ERROR -> CONNECTING -> IDLE. Raises CameraNotFound / CameraIOError
        (state returns to DISCONNECTED) or InvalidState if already connecting."""
        raise NotImplementedError

    async def disconnect(self) -> CameraStatus:
        """Any state -> DISCONNECTED. Idempotent. Releases any lease holder's access."""
        raise NotImplementedError

    @property
    def state(self) -> CameraState:
        raise NotImplementedError

    def status(self) -> CameraStatus:
        raise NotImplementedError

    async def transition(self, to: CameraState) -> CameraState:
        """Validated state change (see class docstring). Returns the previous state."""
        raise NotImplementedError

    # generic op --------------------------------------------------------------
    async def call(
        self,
        fn: Callable[[CameraBackend], T],
        *,
        priority: Priority = Priority.CONTROL,
        timeout: float = 30.0,  # noqa: ASYNC109
        owner: str | None = None,
    ) -> T:
        """Run ``fn(backend)`` on the worker thread and return its result.

        Raises CameraNotConnected if no backend is open, CameraBusy if a lease is held
        by someone other than ``owner``, CameraTimeout on timeout (-> ERROR + reset),
        or whatever AppError the backend raised. A CameraIOError/CameraNotConnected from
        the backend moves the service to DISCONNECTED.
        """
        raise NotImplementedError

    # convenience wrappers ----------------------------------------------------
    async def list_settings(self, *, refresh: bool = False) -> list[ConfigWidget]:
        """Cached config tree (flat access via widget.path). ``refresh`` bypasses the cache."""
        raise NotImplementedError

    async def get_setting(self, name: str) -> ConfigWidget:
        """Cached leaf widget. Raises SettingNotFound."""
        raise NotImplementedError

    async def set_setting(self, name: str, value: str | int | float | bool) -> ConfigWidget:
        """Set a widget, invalidate its cache entry, publish SETTING_CHANGED, and return
        the re-read widget."""
        raise NotImplementedError

    async def capture(
        self,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        owner: str | None = None,
    ) -> CameraFilePath:
        """CAPTURING transition (auto-pauses live view and restores it), capture at CAPTURE
        priority, publish CAPTURE_STARTED / CAPTURE_COMPLETE, wait for the FILE_ADDED event
        instead of sleeping. ``timeout`` defaults to config.camera.capture_timeout_s."""
        raise NotImplementedError

    async def preview_frame(self) -> bytes:
        """One live-view JPEG at PREVIEW priority. Coalesced: at most one pending request;
        concurrent callers await the same frame. Raises InvalidState unless LIVEVIEW."""
        raise NotImplementedError

    def lease(self, owner: str) -> AbstractAsyncContextManager[Lease]:
        """Exclusive access for a long operation; others get CameraBusy (409).
        Released on exit, including on exception/cancellation."""
        raise NotImplementedError
