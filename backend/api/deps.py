"""Dependency getters reading services from ``app.state`` (set by the app factory).

Feature services are built lazily, once per app, via ``service_dep`` (no shared file edits)::

    # backend/api/v1/widgets.py  (auto-discovered; expose ``router`` and/or ``ws_router``)
    from typing import Annotated
    from fastapi import APIRouter, Depends
    from backend.api.deps import service_dep
    from backend.features.widgets import WidgetService

    get_widgets = service_dep(
        "widgets", lambda s: WidgetService(s.camera_service, s.event_bus, s.output_dir)
    )
    router = APIRouter(prefix="/widgets", tags=["widgets"])

    @router.get("")
    async def list_widgets(svc: Annotated[WidgetService, Depends(get_widgets)]): ...

The same dependency works in ``@ws_router.websocket(...)`` handlers. The factory receives
``app.state`` (config_store, camera_service, event_bus, job_manager, data_dir, output_dir).
Services with ``aclose()``/``close()`` are closed at shutdown in reverse creation order.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

from fastapi import Depends, Request, WebSocket
from starlette.datastructures import State
from starlette.requests import HTTPConnection

from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.events import EventBus
from backend.core.jobs import JobManager
from backend.core.registry import ServiceRegistry

T = TypeVar("T")


def get_config_store(request: Request) -> ConfigStore:
    return request.app.state.config_store


def get_camera_service(request: Request) -> CameraService:
    return request.app.state.camera_service


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager


def ws_state(websocket: WebSocket) -> Any:
    """``app.state`` for a WebSocket handler (use ``ws_state(ws).event_bus`` etc.)."""
    return websocket.app.state


def ws_get_event_bus(websocket: WebSocket) -> EventBus:
    return websocket.app.state.event_bus


def ws_get_camera_service(websocket: WebSocket) -> CameraService:
    return websocket.app.state.camera_service


def get_services(conn: HTTPConnection) -> ServiceRegistry:
    """Works for both HTTP requests and WebSockets."""
    return conn.app.state.services


def get_output_dir(conn: HTTPConnection) -> Path:
    return conn.app.state.output_dir


def get_data_dir(conn: HTTPConnection) -> Path:
    return conn.app.state.data_dir


# WebSocket variants (same implementation; ``HTTPConnection`` covers both)
ws_get_services = get_services
ws_get_output_dir = get_output_dir
ws_get_data_dir = get_data_dir


def service_dep(name: str, factory: Callable[[State], T]) -> Callable[[HTTPConnection], T]:
    """Dependency that builds feature service ``name`` once per app from ``app.state``."""

    def dependency(conn: HTTPConnection) -> T:
        state = conn.app.state
        return get_services(conn).get(name, lambda: factory(state))

    dependency.__name__ = f"get_{name}_service"
    return dependency


ConfigStoreDep = Annotated[ConfigStore, Depends(get_config_store)]
CameraServiceDep = Annotated[CameraService, Depends(get_camera_service)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
ServicesDep = Annotated[ServiceRegistry, Depends(get_services)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]
DataDirDep = Annotated[Path, Depends(get_data_dir)]
