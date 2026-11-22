"""Versioned API routers (mounted under /api/v1 by the app factory).

Every module in this package is auto-discovered (sorted by name). A module may expose a
module-level ``router: APIRouter`` and/or ``ws_router: APIRouter`` (WebSocket routes); each is
included as-is. Import errors propagate so a broken module fails app startup loudly.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable
from types import ModuleType

from fastapi import APIRouter

ROUTER_ATTRS = ("router", "ws_router")


def discover_modules(package: ModuleType) -> list[ModuleType]:
    """Import every submodule of ``package``, sorted by name. Errors are not swallowed."""
    names = sorted(m.name for m in pkgutil.iter_modules(package.__path__))
    return [importlib.import_module(f"{package.__name__}.{n}") for n in names]


def build_router(modules: Iterable[ModuleType]) -> APIRouter:
    """Include each module's ``router`` / ``ws_router`` (when an ``APIRouter``) in order."""
    root = APIRouter()
    for mod in modules:
        for attr in ROUTER_ATTRS:
            r = getattr(mod, attr, None)
            if isinstance(r, APIRouter):
                root.include_router(r)
    return root


api_router = build_router(discover_modules(importlib.import_module(__name__)))
