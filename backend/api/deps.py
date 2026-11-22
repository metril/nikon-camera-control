"""Dependency getters reading services from ``app.state`` (set by the app factory)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request, WebSocket

from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.events import EventBus
from backend.core.jobs import JobManager


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


ConfigStoreDep = Annotated[ConfigStore, Depends(get_config_store)]
CameraServiceDep = Annotated[CameraService, Depends(get_camera_service)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
JobManagerDep = Annotated[JobManager, Depends(get_job_manager)]
