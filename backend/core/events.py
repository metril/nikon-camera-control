"""EventBus: typed fan-out of {type, ts, data} events to WebSocket clients and services."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

from backend.api.schemas.common import Event, EventType

log = logging.getLogger(__name__)


class Subscription:
    """Async iterator (and async context manager) over events for one subscriber.

    Backed by a bounded asyncio.Queue. When the queue is full the subscriber is
    dropped (removed from the bus, ``dropped`` is True) rather than blocking the
    publisher; iteration then ends (StopAsyncIteration) so the WebSocket handler
    can close the socket and the client can reconnect.
    """

    def __init__(self, bus: EventBus, queue: asyncio.Queue[Event | None]) -> None:
        self._bus = bus
        self._queue = queue
        self._dropped = False
        self._ended = False

    @property
    def dropped(self) -> bool:
        """True if the bus dropped this subscriber because its queue overflowed."""
        return self._dropped

    def _offer(self, event: Event) -> bool:
        """Enqueue without blocking; False if full or already ended."""
        if self._ended:
            return True
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        return True

    def _end(self) -> None:
        """Discard buffered events and wake the iterator with the end sentinel."""
        if self._ended:
            return
        self._ended = True
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)

    def close(self) -> None:
        """Unsubscribe. Idempotent."""
        self._bus._remove(self)
        self._end()

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        item = await self._queue.get()
        if item is None:
            # keep the sentinel so repeated calls keep raising instead of hanging
            self._queue.put_nowait(None)
            raise StopAsyncIteration
        return item

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class EventBus:
    """Thread-safe fan-out of events.

    - ``publish`` may be called from any thread. Off-loop it hops with
      ``loop.call_soon_threadsafe``; on-loop it delivers directly. It never blocks and
      never raises (before the loop is bound or after close() it drops the event).
    - The bus binds to the running loop on first ``subscribe`` or via ``bind_loop``.
    - Each subscriber has a bounded queue (``queue_size``); when full that subscriber is
      dropped and others are unaffected.
    - Events carry counters/ids only, never payload blobs.
    """

    def __init__(
        self, *, queue_size: int = 256, loop: asyncio.AbstractEventLoop | None = None
    ) -> None:
        self._queue_size = queue_size
        self._loop = loop
        self._subs: set[Subscription] = set()
        self._closed = False

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the loop used for cross-thread publishes (call from lifespan startup)."""
        self._loop = loop

    def publish(self, type: EventType, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all subscribers. Thread-safe, non-blocking."""
        if self._closed:
            log.debug("event %s dropped: bus closed", type)
            return
        loop = self._loop
        if loop is None:
            log.debug("event %s dropped: no loop bound", type)
            return
        event = Event(type=type, data=dict(data or {}))
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event)
            return
        try:
            loop.call_soon_threadsafe(self._deliver, event)
        except RuntimeError:
            log.debug("event %s dropped: loop closed", type)

    def _deliver(self, event: Event) -> None:
        if self._closed:
            return
        for sub in list(self._subs):  # snapshot: safe against concurrent unsubscribe
            if not sub._offer(event):
                log.warning("dropping slow event subscriber")
                self._subs.discard(sub)
                sub._dropped = True
                sub._end()

    def _remove(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def subscribe(self) -> Subscription:
        """Register a new subscriber. Must be called on the event loop thread."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        sub = Subscription(self, asyncio.Queue(maxsize=self._queue_size))
        if self._closed:
            sub._end()
        else:
            self._subs.add(sub)
        return sub

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def close(self) -> None:
        """End all subscriptions (iterators finish) and make publish a no-op."""
        self._closed = True
        subs, self._subs = list(self._subs), set()
        for sub in subs:
            sub._end()
