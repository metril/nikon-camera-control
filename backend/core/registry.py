"""Per-app registry of lazily created feature services (``app.state.services``)."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class ServiceRegistry:
    """Creates each named service once and closes them in reverse creation order."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def get(self, name: str, factory: Callable[[], T]) -> T:
        """Return the service ``name``, building it with ``factory`` on first use.

        Synchronous with no awaits, so it is atomic on the event loop.
        """
        try:
            return self._services[name]
        except KeyError:
            pass
        svc = factory()
        self._services[name] = svc
        return svc

    def peek(self, name: str) -> Any | None:
        """The service ``name`` if it was already built, else None (never builds)."""
        return self._services.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._services

    async def aclose(self) -> None:
        """Close services newest-first (``aclose`` preferred over ``close``); log failures."""
        items = list(self._services.items())
        self._services.clear()
        for name, svc in reversed(items):
            try:
                closer = getattr(svc, "aclose", None) or getattr(svc, "close", None)
                if closer is None:
                    continue
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("closing service %r failed", name)
