"""CameraService: the single owner of the camera, its state machine and its worker thread.

Design contract
---------------
- One worker thread runs every blocking ``CameraBackend`` call, fed by a
  ``queue.PriorityQueue``. Priority order (lower runs first): CONTROL < CAPTURE <
  KEEPALIVE < PREVIEW; FIFO within a priority (sequence counter). Async callers await a
  future resolved with ``loop.call_soon_threadsafe``.
- ``call(fn, priority=, timeout=)`` is the one generic way to run a backend op. If the op
  does not finish within ``timeout`` the awaiting caller gets ``CameraTimeout`` and the item
  is marked abandoned (its late result is discarded; every coalesced waiter is woken with the
  same error). If the item was already running, queued items are failed with CameraTimeout,
  the service moves to ERROR, and once the stuck call returns the worker itself resets the
  backend (close + reopen) and the state returns to IDLE. An item that times out while still
  queued is just skipped: no ERROR, no reset. There is only ever one live worker thread, so
  timeouts cannot pile up threads. If the stuck call never returns the service stays in
  ERROR; ``disconnect()`` waits a bounded time for an in-flight call, then abandons that
  worker (it exits by itself when the call finally returns, and never closes a backend a
  newer worker owns) and the next ``connect()`` starts a fresh one.
- Every state change goes through one validated path (``core.state.can_transition``;
  ``transition`` is its public form), is published on the bus as CAMERA_STATE
  ({state, previous}), plus CAMERA_CONNECTED / CAMERA_DISCONNECTED where relevant.
  Invalid transitions raise InvalidState; nothing writes ``_state`` anywhere else.
- Keepalive: a task per connection reads ``camera.keepalive_interval_s`` /
  ``keepalive_enabled`` live from the config store every cycle and, at KEEPALIVE priority,
  reads the ``batterylevel`` widget (publishing BATTERY when it changes). It is skipped
  unless the state is IDLE/BUSY, or if any backend call ran within the interval. Three
  consecutive keepalive failures, or any CameraIOError/CameraNotConnected from a call,
  move to DISCONNECTED, publish CAMERA_DISCONNECTED and start a reconnect loop
  (``camera.connect_retries`` attempts, exponential backoff from
  ``camera.reconnect_interval_s``) that ends in IDLE on success; an explicit
  ``disconnect()`` stops it.
- ``disconnect()`` stops keepalive/reconnect first, flips state, fails queued callers with
  CameraNotConnected, closes the backend on the worker and waits (polling, bounded, never
  joining under a lock) - abandoning the worker if it is stuck.
- Config cache: ``list_settings``/``get_setting`` are served from a per-connection cache;
  ``set_setting`` invalidates it and publishes SETTING_CHANGED. Cleared on disconnect.
- ``lease(owner)`` grants exclusive use for long operations (time-lapse, bulb, focus
  stack, recording). Exact rule: while a lease is held by X, ``call`` with priority CONTROL
  or CAPTURE and ``owner != X`` (None included) raises CameraBusy; so do ``capture`` and
  ``set_setting`` without ``owner=X``. Always allowed: KEEPALIVE/PREVIEW priority,
  ``preview_frame``, ``status()``, and the read-only ``list_settings``/``get_setting``. A
  second ``lease`` raises CameraBusy. ``disconnect()`` drops the lease.
- ``preview_frame`` is coalesced: at most one PREVIEW item is pending; concurrent callers
  share the same result.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import functools
import itertools
import logging
import queue
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from backend.api.schemas.common import EventType
from backend.camera.backend import (
    CameraBackend,
    CameraFilePath,
    ConfigType,
    ConfigWidget,
)
from backend.camera.backend import EventType as CamEventType
from backend.core.config_store import ConfigStore
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraIOError,
    CameraNotConnected,
    CameraTimeout,
    InvalidState,
    SettingNotFound,
)
from backend.core.events import EventBus
from backend.core.state import CameraState, can_transition

T = TypeVar("T")

log = logging.getLogger(__name__)

_S = CameraState

# Widgets whose change can alter OTHER widgets' choices/values on a real body (exposure program
# changes the usable aperture/shutter, image quality the size options, ...). ``set_setting`` drops
# the whole settings cache after writing one of these; any other write updates just that widget.
MODE_LIKE_SETTINGS: frozenset[str] = frozenset(
    {
        "expprogram",
        "autoexposuremode",
        "capturemode",
        "drivemode",
        "focusmode",
        "focusmode2",
        "imagequality",
        "imagesize",
        "liveviewsize",
        "flashmode",
    }
)
_LIVE_STATES = frozenset({_S.IDLE, _S.LIVEVIEW, _S.CAPTURING, _S.RECORDING, _S.BULB, _S.BUSY})
_KEEPALIVE_STATES = frozenset({_S.IDLE, _S.BUSY})
_PREVIEW_STATES = frozenset({_S.LIVEVIEW, _S.RECORDING})
_KEEPALIVE_FAILURES = 3
_KEEPALIVE_TIMEOUT_S = 10.0
_PREVIEW_TIMEOUT_S = 10.0
_MAX_BACKOFF_S = 30.0


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
    serial: str | None = None
    last_activity: datetime | None = None


class Lease:
    """Handle yielded by ``CameraService.lease``."""

    def __init__(self, owner: str) -> None:
        self.owner = owner


@dataclass(eq=False)
class _Item:
    seq: int
    priority: int
    fn: Callable[[_Worker], Any] | None  # None = stop sentinel
    loop: Any  # AbstractEventLoop; None for the stop sentinel
    fut: Any  # asyncio.Future[Any]; None for the stop sentinel
    escalate: bool = True  # timeout -> ERROR + reset
    lock: threading.Lock = field(default_factory=threading.Lock)
    finished: bool = False
    abandoned: bool = False
    started: bool = False
    reset: bool = True

    def try_abandon(self, *, reset: bool) -> bool:
        """Mark abandoned. ``reset`` only applies if the worker already started the item;
        a still-queued item is simply skipped by the worker."""
        with self.lock:
            if self.finished or self.abandoned:
                return False
            self.abandoned = True
            self.reset = reset and self.started
            return True

    def begin(self) -> bool:
        """Worker side: False if the item was abandoned while queued (skip it)."""
        with self.lock:
            if self.abandoned:
                return False
            self.started = True
            return True

    def deliver(self, result: Any, exc: BaseException | None) -> None:
        fut, loop = self.fut, self.loop
        if fut is None or loop is None:
            return

        def _set() -> None:
            if fut.done():
                return
            if exc is not None:
                fut.set_exception(exc)
            else:
                fut.set_result(result)

        with contextlib.suppress(RuntimeError):  # loop already closed
            loop.call_soon_threadsafe(_set)


class _Worker:
    """One dedicated thread consuming a PriorityQueue; owns the backend instance."""

    def __init__(self, svc: CameraService) -> None:
        self._svc = svc
        self.queue: queue.PriorityQueue[tuple[int, int, _Item]] = queue.PriorityQueue()
        self._seq = itertools.count(1)
        self.backend: CameraBackend | None = None
        self.inflight: _Item | None = None
        self.stopped = False
        self.gen = next(svc._generations)
        self.thread = threading.Thread(
            target=self._run, name=f"{svc._thread_prefix}-{self.gen}", daemon=True
        )
        self.thread.start()

    # called on the event loop ---------------------------------------------------------
    def submit(
        self,
        fn: Callable[[_Worker], Any],
        priority: int,
        *,
        escalate: bool = True,
    ) -> _Item:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark retrieved
        item = _Item(next(self._seq), priority, fn, loop, fut, escalate=escalate)
        self.queue.put((priority, item.seq, item))
        return item

    def fail_queued(self, exc: Callable[[], Exception]) -> None:
        sentinel: tuple[int, int, _Item] | None = None
        while True:
            try:
                entry = self.queue.get_nowait()
            except queue.Empty:
                break
            if entry[2].fn is None:
                sentinel = entry
            else:
                entry[2].deliver(None, exc())
        if sentinel is not None:
            self.queue.put(sentinel)

    def fail_inflight(self, exc: Callable[[], Exception]) -> bool:
        """Fail the running call's awaiting caller; returns True if one was running."""
        item = self.inflight
        if item is None:
            return False
        if item.try_abandon(reset=False):
            item.deliver(None, exc())
        return True

    def stop(self) -> None:
        self.stopped = True
        self.queue.put((-1, 0, _Item(0, -1, None, None, None)))

    # worker thread --------------------------------------------------------------------
    def require(self) -> CameraBackend:
        if self.backend is None:
            raise CameraNotConnected()
        return self.backend

    def _run(self) -> None:
        try:
            while True:
                _, _, item = self.queue.get()
                if item.fn is None:
                    break
                if not item.begin():
                    continue  # abandoned while queued
                self.inflight = item
                result: Any = None
                exc: BaseException | None = None
                try:
                    result = item.fn(self)
                except Exception as e:
                    exc = e
                if self._svc._worker is self:  # late results from old generations are ignored
                    self._svc._last_activity = time.monotonic()
                with item.lock:
                    abandoned = item.abandoned
                    if not abandoned:
                        item.finished = True
                    reset = item.reset
                self.inflight = None
                if abandoned:
                    self._after_abandoned(reset)
                else:
                    item.deliver(result, exc)
                if self.stopped:
                    break
        finally:
            self._cleanup()

    def _after_abandoned(self, reset: bool) -> None:
        backend = self.backend
        if backend is None:
            return
        if self.stopped or not reset:
            self.backend = None
            self._close_backend(backend)
            return
        ok = True
        try:
            backend.close()
            backend.open()
        except Exception:
            ok = False
        loop = self._svc._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._svc._on_reset_done, self, ok)

    def _cleanup(self) -> None:
        self.stopped = True
        self.fail_queued(CameraNotConnected)
        backend = self.backend
        self.backend = None
        if backend is not None:
            self._close_backend(backend)

    def _close_backend(self, backend: CameraBackend) -> None:
        """Close unless a newer worker now owns this very backend object."""
        current = self._svc._worker
        if current is not None and current is not self and current.backend is backend:
            return
        with contextlib.suppress(Exception):
            backend.close()


class CameraService:
    def __init__(
        self,
        backend_factory: Callable[[], CameraBackend],
        config_store: ConfigStore,
        event_bus: EventBus,
        *,
        event_quiet_window_s: float = 1.0,
        disconnect_wait_s: float = 3.0,
    ) -> None:
        """``backend_factory`` is called on each (re)connect to get a fresh backend
        (real gphoto2 or FakeCamera). It is invoked on the worker thread.
        ``event_quiet_window_s``: after a capture, stop draining camera events once this
        long passes with no new event. ``disconnect_wait_s``: how long ``disconnect`` waits
        for an in-flight call before abandoning the worker."""
        self._factory = backend_factory
        self._config = config_store
        self._bus = event_bus
        self._state = CameraState.DISCONNECTED
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker: _Worker | None = None
        self._last_activity = 0.0
        self._model: str | None = None
        self._serial: str | None = None
        self._connected_at: float | None = None
        self._last_error: str | None = None
        self._lease_owner: str | None = None
        self._lease_token: object | None = None
        self._preview_item: _Item | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._battery: Any = None
        self._settings_tree: list[ConfigWidget] | None = None
        self._settings_map: dict[str, ConfigWidget] = {}
        self._cache_epoch = 0
        self._close_wait_s = 2.0
        self._quiet_window_s = event_quiet_window_s
        self._disconnect_wait_s = disconnect_wait_s
        self._generations = itertools.count(1)
        self._thread_prefix = f"camera-worker-{id(self):x}"
        self._stop_wait_s = 2.0

    # lifecycle ---------------------------------------------------------------
    async def start(self) -> None:
        """Bind the bus to the running loop and start the worker thread.
        Does not connect. Idempotent. (Keepalive runs per connection.)"""
        self._loop = asyncio.get_running_loop()
        self._bus.bind_loop(self._loop)
        self._ensure_worker()

    async def stop(self) -> None:
        """Disconnect, stop keepalive/reconnect tasks, stop the worker (bounded wait)."""
        await self.disconnect()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.stop()
            await self._wait_thread(worker, self._stop_wait_s)

    async def connect(self) -> CameraStatus:
        """DISCONNECTED/ERROR -> CONNECTING -> IDLE. Raises CameraNotFound / CameraIOError
        (state returns to DISCONNECTED) or InvalidState if already connecting.
        Idempotent when already connected."""
        if self._state == _S.CONNECTING:
            raise InvalidState("Camera is already connecting")
        if self._state not in (_S.DISCONNECTED, _S.ERROR):
            return self.status()
        await self._cancel_task("_reconnect_task")
        await self._do_connect()
        return self.status()

    async def disconnect(self) -> CameraStatus:
        """Any state -> DISCONNECTED. Idempotent. Releases any lease holder's access."""
        await self._cancel_task("_reconnect_task")
        await self._cancel_task("_keepalive_task")
        was_live = self._state in _LIVE_STATES or self._state == _S.ERROR
        self._try_state(_S.DISCONNECTED)
        if was_live:
            self._bus.publish(EventType.CAMERA_DISCONNECTED, {"reason": "disconnect"})
        self._invalidate_cache()
        self._lease_owner = None
        self._lease_token = None
        shared, self._preview_item = self._preview_item, None
        if shared is not None:
            shared.deliver(None, CameraNotConnected())
        self._connected_at = None
        worker = self._worker
        if worker is None:
            return self.status()
        worker.fail_queued(CameraNotConnected)
        if worker.inflight is not None:  # give the running call a bounded chance to finish
            deadline = time.monotonic() + self._disconnect_wait_s
            while worker.inflight is not None and time.monotonic() < deadline:  # noqa: ASYNC110
                await asyncio.sleep(0.005)
        if worker.fail_inflight(CameraNotConnected):
            self._abandon_worker(worker)  # stuck in a call: it closes the backend on exit
        elif worker.backend is not None:
            item = worker.submit(self._close_job, Priority.CONTROL, escalate=False)
            await asyncio.wait({item.fut}, timeout=self._close_wait_s)
            if not item.fut.done():
                item.try_abandon(reset=False)
                self._abandon_worker(worker)
        return self.status()

    @property
    def state(self) -> CameraState:
        return self._state

    def status(self) -> CameraStatus:
        return CameraStatus(
            state=self._state,
            connected=self._state in _LIVE_STATES,
            model=self._model,
            leased_by=self._lease_owner,
            last_error=self._last_error,
            connected_at=self._connected_at,
            serial=self._serial if self._state in _LIVE_STATES else None,
            last_activity=self._last_activity_dt(),
        )

    def _last_activity_dt(self) -> datetime | None:
        if self._state not in _LIVE_STATES or not self._last_activity:
            return None
        return datetime.fromtimestamp(time.time() - (time.monotonic() - self._last_activity), UTC)

    async def transition(self, to: CameraState) -> CameraState:
        """Validated state change (see class docstring). Returns the previous state.

        Leaving LIVEVIEW for IDLE also switches the camera's viewfinder off (best effort, at
        CONTROL priority and regardless of any lease: it only undoes our own preview)."""
        prev = self._set_state(to)
        if prev == _S.LIVEVIEW and to == _S.IDLE:
            await self._end_preview()
        return prev

    async def _end_preview(self) -> None:
        try:
            await self._run(lambda b: b.end_preview(), Priority.CONTROL, 10.0)
        except AppError as e:
            log.debug("end_preview failed: %s", e)

    # state machine (the only writers of self._state) -----------------------------
    def _set_state(self, to: CameraState) -> CameraState:
        prev = self._state
        if not can_transition(prev, to):
            raise InvalidState(
                f"Cannot go from {prev.value} to {to.value}",
                details={"from": prev.value, "to": to.value},
            )
        self._state = to
        self._bus.publish(EventType.CAMERA_STATE, {"state": to.value, "previous": prev.value})
        return prev

    def _try_state(self, to: CameraState) -> bool:
        if not can_transition(self._state, to):
            return False
        self._set_state(to)
        return True

    # connection ----------------------------------------------------------------
    @staticmethod
    def _close_job(w: _Worker) -> None:
        backend, w.backend = w.backend, None
        if backend is not None:
            with contextlib.suppress(Exception):
                backend.close()

    def _ensure_worker(self) -> _Worker:
        worker = self._worker
        if worker is None or worker.stopped or not worker.thread.is_alive():
            worker = self._worker = _Worker(self)
        return worker

    def _abandon_worker(self, worker: _Worker) -> None:
        worker.stop()
        if self._worker is worker:
            self._worker = None

    async def _wait_thread(self, worker: _Worker, bound: float) -> None:
        deadline = time.monotonic() + bound
        while worker.thread.is_alive() and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(0.005)

    async def _cancel_task(self, attr: str) -> None:
        task: asyncio.Task[None] | None = getattr(self, attr)
        setattr(self, attr, None)
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if me is not None and me.cancelling() > 0:
                raise  # we are being cancelled ourselves, not just the inner task
        except Exception:  # noqa: S110
            pass

    def _open_job(self, w: _Worker) -> tuple[str, str | None]:
        old, w.backend = w.backend, None
        if old is not None:
            with contextlib.suppress(Exception):
                old.close()
        backend = self._factory()
        try:
            backend.open()
            model = backend.model()
            serial: str | None = None
            try:
                value = backend.get_config("serialnumber").value
                serial = None if value is None else str(value)
            except Exception:
                serial = None
        except BaseException:
            with contextlib.suppress(Exception):
                backend.close()
            raise
        w.backend = backend
        return model, serial

    async def _do_connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        worker = self._ensure_worker()
        self._set_state(_S.CONNECTING)
        try:
            item = worker.submit(self._open_job, Priority.CONTROL, escalate=False)
            model, serial = await self._await_item(
                worker, item, self._config.config.camera.connect_timeout_s
            )
        except BaseException as e:
            self._last_error = str(e) or type(e).__name__
            self._try_state(_S.DISCONNECTED)
            worker.submit(self._close_job, Priority.CONTROL, escalate=False)
            raise
        self._model, self._serial = model, serial
        self._connected_at = time.time()
        self._last_activity = time.monotonic()
        self._last_error = None
        self._battery = None
        self._invalidate_cache()
        self._set_state(_S.IDLE)
        self._bus.publish(EventType.CAMERA_CONNECTED, {"model": model, "serial": serial})
        self._keepalive_task = asyncio.create_task(self._keepalive_loop(), name="camera-keepalive")

    def _lost(self, reason: str) -> None:
        """Link lost: DISCONNECTED + event + reconnect loop. Synchronous and idempotent."""
        if self._state in (_S.DISCONNECTED, _S.CONNECTING):
            return
        self._last_error = reason
        self._try_state(_S.DISCONNECTED)
        self._bus.publish(EventType.CAMERA_DISCONNECTED, {"reason": reason})
        self._connected_at = None
        self._invalidate_cache()
        self._preview_item = None
        ka = self._keepalive_task
        self._keepalive_task = None
        if ka is not None and ka is not asyncio.current_task():
            ka.cancel()
        worker = self._worker
        if worker is not None:
            worker.fail_queued(CameraNotConnected)
            worker.fail_inflight(CameraNotConnected)
            worker.submit(self._close_job, Priority.CONTROL, escalate=False)
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(
                self._reconnect_loop(), name="camera-reconnect"
            )

    async def _reconnect_loop(self) -> None:
        attempt = 0
        while attempt < self._config.config.camera.connect_retries:
            cfg = self._config.config.camera
            await asyncio.sleep(min(cfg.reconnect_interval_s * (2**attempt), _MAX_BACKOFF_S))
            attempt += 1
            if self._state != _S.DISCONNECTED:
                return
            try:
                await self._do_connect()
                return
            except Exception:  # noqa: S112
                continue

    def _on_reset_done(self, worker: _Worker, ok: bool) -> None:
        if worker is not self._worker or self._state != _S.ERROR:
            return
        if ok:
            self._invalidate_cache()
            self._try_state(_S.IDLE)
        else:
            self._lost("backend reset failed")

    # generic op --------------------------------------------------------------
    def _check_lease(self, priority: int, owner: str | None) -> None:
        if (
            self._lease_owner is not None
            and owner != self._lease_owner
            and priority in (Priority.CONTROL, Priority.CAPTURE)
        ):
            raise CameraBusy(details={"leased_by": self._lease_owner})

    async def _await_item(self, worker: _Worker, item: _Item, timeout: float | None) -> Any:  # noqa: ASYNC109  # noqa: ASYNC109
        fut = item.fut
        await asyncio.wait({fut}, timeout=timeout)
        if not fut.done():
            if item.try_abandon(reset=item.escalate):
                if item.escalate and item.started:  # only the in-flight call stalls the camera
                    self._on_timeout(worker)
                item.deliver(None, CameraTimeout())  # wake every coalesced waiter
                raise CameraTimeout()
            await asyncio.wait({fut})  # result already in flight
        return fut.result()

    def _on_timeout(self, worker: _Worker) -> None:
        if worker is not self._worker:
            return
        self._last_error = "camera operation timed out"
        if self._state in _LIVE_STATES:
            self._try_state(_S.ERROR)
        worker.fail_queued(CameraTimeout)
        self._preview_item = None

    async def _run(
        self,
        fn: Callable[[CameraBackend], T],
        priority: int,
        timeout: float | None,  # noqa: ASYNC109
    ) -> T:
        worker = self._worker
        if worker is None or self._state in (_S.DISCONNECTED, _S.CONNECTING):
            raise CameraNotConnected()
        item = worker.submit(lambda w: fn(w.require()), priority)
        return await self._finish(worker, item, timeout)

    async def _finish(self, worker: _Worker, item: _Item, timeout: float | None) -> Any:  # noqa: ASYNC109
        try:
            return await self._await_item(worker, item, timeout)
        except (CameraIOError, CameraNotConnected) as e:
            if worker is self._worker:
                self._lost(e.message)
            raise

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
        by someone other than ``owner`` and priority is CONTROL/CAPTURE, CameraTimeout on
        timeout (-> ERROR + reset), or whatever AppError the backend raised. A
        CameraIOError/CameraNotConnected from the backend moves the service to DISCONNECTED.
        """
        self._check_lease(priority, owner)
        return await self._run(fn, priority, timeout)

    # settings -------------------------------------------------------------------
    def _invalidate_cache(self) -> None:
        self._cache_epoch += 1
        self._settings_tree = None
        self._settings_map = {}

    def invalidate_settings(self) -> None:
        """Drop the whole settings cache (next read re-fetches the config tree)."""
        self._invalidate_cache()

    def _store_widget(self, widget: ConfigWidget) -> None:
        """Update one widget in the cache (map and tree) without refetching the tree."""
        self._cache_epoch += 1  # reads in flight started before this must not overwrite it
        if self._settings_tree is None:
            return
        self._settings_map[widget.name] = widget

        def swap(ws: tuple[ConfigWidget, ...] | list[ConfigWidget]) -> list[ConfigWidget]:
            return [
                widget
                if w.name == widget.name and w.type != ConfigType.SECTION
                else (replace(w, children=tuple(swap(w.children))) if w.children else w)
                for w in ws
            ]

        self._settings_tree = swap(self._settings_tree)

    @staticmethod
    def _flatten(widgets: list[ConfigWidget] | tuple[ConfigWidget, ...]) -> dict[str, ConfigWidget]:
        out: dict[str, ConfigWidget] = {}
        for w in widgets:
            if w.children:
                out.update(CameraService._flatten(w.children))
            if w.type != ConfigType.SECTION:
                out[w.name] = w
        return out

    async def list_settings(self, *, refresh: bool = False) -> list[ConfigWidget]:
        """Cached config tree (flat access via widget.path). ``refresh`` bypasses the cache.
        Read-only: allowed during a lease."""
        if self._settings_tree is not None and not refresh:
            return self._settings_tree
        epoch = self._cache_epoch
        tree = await self._run(lambda b: b.list_config(), Priority.CONTROL, 30.0)
        if epoch == self._cache_epoch:
            self._settings_tree = tree
            self._settings_map = self._flatten(tree)
        return tree

    async def get_setting(self, name: str) -> ConfigWidget:
        """Cached leaf widget. Raises SettingNotFound. Read-only: allowed during a lease."""
        if self._settings_tree is None:
            await self.list_settings()
        widget = self._settings_map.get(name)
        if widget is not None:
            return widget
        epoch = self._cache_epoch
        widget = await self._run(lambda b: b.get_config(name), Priority.CONTROL, 30.0)
        if epoch == self._cache_epoch:
            self._settings_map[name] = widget
        return widget

    async def refresh_setting(self, name: str) -> ConfigWidget:
        """Fresh single-widget read from the camera (one ``get_config``), cache updated."""
        widget = await self._run(lambda b: b.get_config(name), Priority.CONTROL, 30.0)
        self._store_widget(widget)
        return widget

    async def set_setting(
        self, name: str, value: str | int | float | bool, *, owner: str | None = None
    ) -> ConfigWidget:
        """Set a widget, publish SETTING_CHANGED, and return the re-read widget. ``owner`` is
        the lease holder, if any. Only that widget is updated in the cache, except for the
        ``MODE_LIKE_SETTINGS`` whose change can alter other widgets' choices: those drop the
        whole cache."""
        self._check_lease(Priority.CONTROL, owner)

        def _set(b: CameraBackend) -> ConfigWidget:
            b.set_config(name, value)
            return b.get_config(name)

        widget = await self._run(_set, Priority.CONTROL, 30.0)
        if name in MODE_LIKE_SETTINGS:
            self._invalidate_cache()
        else:
            self._store_widget(widget)
        self._bus.publish(EventType.SETTING_CHANGED, {"name": name, "value": widget.value})
        return widget

    # capture / preview ------------------------------------------------------------
    async def capture(
        self,
        *,
        timeout: float | None = None,  # noqa: ASYNC109
        owner: str | None = None,
    ) -> list[CameraFilePath]:
        """CAPTURING transition, capture at CAPTURE priority, then drain camera events until
        CAPTURE_COMPLETE, a quiet window with no new event (``event_quiet_window_s``; real
        bodies often swallow CAPTURE_COMPLETE inside capture()) or ``timeout``. The path
        returned by capture() is always included, de-duplicated with every FILE_ADDED
        (RAW+JPEG yields two files); publish CAPTURE_STARTED / CAPTURE_COMPLETE, then
        restore the prior state (IDLE or LIVEVIEW). ``timeout`` defaults to
        config.camera.capture_timeout_s and bounds the capture and, separately, the drain."""
        self._check_lease(Priority.CAPTURE, owner)
        t = timeout if timeout is not None else self._config.config.camera.capture_timeout_s
        prior = await self.transition(_S.CAPTURING)
        self._bus.publish(EventType.CAPTURE_STARTED, {})

        def _do(b: CameraBackend) -> list[CameraFilePath]:
            files = [b.capture()]
            b.invalidate_preview()  # a capture may drop the body out of live view
            deadline = last = time.monotonic()
            deadline += t
            while True:
                now = time.monotonic()
                remaining = min(deadline - now, self._quiet_window_s - (now - last))
                if remaining <= 0:
                    break
                ev = b.wait_for_event(min(remaining, 0.5))
                if ev.type == CamEventType.CAPTURE_COMPLETE:
                    break
                if ev.type == CamEventType.TIMEOUT:
                    continue
                last = time.monotonic()
                if ev.type == CamEventType.FILE_ADDED and ev.file is not None:
                    if ev.file not in files:
                        files.append(ev.file)
            return files

        try:
            files = await self._run(_do, Priority.CAPTURE, 2 * t + 1.0)
        finally:
            if self._state == _S.CAPTURING:
                self._try_state(prior)
        self._bus.publish(
            EventType.CAPTURE_COMPLETE,
            {"files": [{"folder": f.folder, "name": f.name} for f in files]},
        )
        return files

    async def preview_frame(self) -> bytes:
        """One live-view JPEG at PREVIEW priority. Coalesced: at most one pending request;
        concurrent callers await the same frame. Raises InvalidState unless LIVEVIEW or
        RECORDING (the D500 keeps streaming previews while recording a movie)."""
        if self._state not in _PREVIEW_STATES:
            raise InvalidState("Live view is not active")
        worker = self._worker
        if worker is None:
            raise CameraNotConnected()
        item = self._preview_item
        if item is None or item.fut is None or item.fut.done():
            item = worker.submit(self._preview_job, Priority.PREVIEW)
            self._preview_item = item
            item.fut.add_done_callback(functools.partial(self._clear_preview_cb, item))
        return cast("bytes", await self._finish(worker, item, _PREVIEW_TIMEOUT_S))

    def _preview_job(self, w: _Worker) -> bytes:
        # Runs on the worker thread. A frame queued before live view ended must not run after
        # end_preview (it would switch the viewfinder back on): state is already left by then.
        if self._state not in _PREVIEW_STATES:
            raise InvalidState("Live view is not active")
        return w.require().capture_preview()

    def _clear_preview_cb(self, item: _Item, _fut: object) -> None:
        if self._preview_item is item:
            self._preview_item = None

    # lease -------------------------------------------------------------------------
    def lease(self, owner: str) -> AbstractAsyncContextManager[Lease]:
        """Exclusive access for a long operation; others get CameraBusy (409).
        Released on exit, including on exception/cancellation. See the module docstring
        for the exact rule."""
        return self._lease(owner)

    @asynccontextmanager
    async def _lease(self, owner: str) -> AsyncIterator[Lease]:
        if self._lease_owner is not None:
            raise CameraBusy(details={"leased_by": self._lease_owner})
        token = object()
        self._lease_owner, self._lease_token = owner, token
        try:
            yield Lease(owner)
        finally:
            if self._lease_token is token:
                self._lease_owner = None
                self._lease_token = None

    # keepalive ---------------------------------------------------------------------
    async def _keepalive_loop(self) -> None:
        failures = 0
        while True:
            cfg = self._config.config.camera
            interval = cfg.keepalive_interval_s
            wait = self._last_activity + interval - time.monotonic()
            if not cfg.keepalive_enabled or self._state not in _KEEPALIVE_STATES:
                await asyncio.sleep(min(interval, 1.0))
                continue
            w = self._worker
            if w is not None and (w.inflight is not None or not w.queue.empty()):
                await asyncio.sleep(min(interval, 0.5))  # never queue behind another call
                continue
            if wait > 0:
                await asyncio.sleep(min(wait, 1.0))
                continue
            try:
                level = await self._run(
                    lambda b: b.get_config("batterylevel").value,
                    Priority.KEEPALIVE,
                    _KEEPALIVE_TIMEOUT_S,
                )
            except SettingNotFound:
                failures = 0
                self._last_activity = time.monotonic()
                continue
            except (CameraIOError, CameraNotConnected):
                return  # _finish already moved to DISCONNECTED
            except (AppError, Exception):
                failures += 1
                if failures >= _KEEPALIVE_FAILURES:
                    self._lost("keepalive failed")
                    return
                continue
            failures = 0
            if level != self._battery:
                self._battery = level
                self._bus.publish(EventType.BATTERY, {"level": level})
