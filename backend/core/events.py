"""EventBus: typed fan-out of {type, ts, data} events to WebSocket clients and services."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.api.schemas.common import Event, EventType


class Subscription:
    """Async iterator over events for one subscriber.

    Contract: backed by a bounded asyncio.Queue. When the queue is full the
    subscriber is dropped (marked closed, removed from the bus) rather than
    blocking the publisher; iteration then ends (StopAsyncIteration) so the
    WebSocket handler can close the socket and the client can reconnect.
    """

    def __init__(self, bus: EventBus, queue: asyncio.Queue[Event | None]) -> None:
        raise NotImplementedError

    @property
    def dropped(self) -> bool:
        """True if the bus dropped this subscriber because its queue overflowed."""
        raise NotImplementedError

    def close(self) -> None:
        """Unsubscribe. Idempotent."""
        raise NotImplementedError

    def __aiter__(self) -> AsyncIterator[Event]:
        raise NotImplementedError

    async def __anext__(self) -> Event:
        raise NotImplementedError


class EventBus:
    """Contract:
    - ``publish`` is thread-safe: callable from the camera worker thread or the event
      loop. From a foreign thread it hops with ``loop.call_soon_threadsafe``. It never
      blocks and never raises (publishing after close() or before the loop is bound is
      a silent no-op).
    - The bus binds to the running loop on first async use (``bind_loop``) or when
      constructed with ``loop``.
    - Each subscriber has a bounded queue (``queue_size``, default 256); when full the
      subscriber is dropped, other subscribers are unaffected.
    - Events carry counters/ids only, never payload blobs (no image bytes).
    """

    def __init__(
        self, *, queue_size: int = 256, loop: asyncio.AbstractEventLoop | None = None
    ) -> None:
        raise NotImplementedError

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the loop used for cross-thread publishes (call from lifespan startup)."""
        raise NotImplementedError

    def publish(self, type: EventType, data: dict[str, Any] | None = None) -> None:
        """Publish an event to all subscribers. Thread-safe, non-blocking."""
        raise NotImplementedError

    def subscribe(self) -> Subscription:
        """Register a new subscriber. Must be called on the event loop thread."""
        raise NotImplementedError

    @property
    def subscriber_count(self) -> int:
        raise NotImplementedError

    def close(self) -> None:
        """End all subscriptions (iterators finish) and make publish a no-op."""
        raise NotImplementedError
