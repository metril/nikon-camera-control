"""Versioned API routers (mounted under /api/v1 by the app factory)."""

from fastapi import APIRouter

from backend.api.v1 import camera, config, events_ws, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(camera.router)
api_router.include_router(config.router)
api_router.include_router(events_ws.router)
