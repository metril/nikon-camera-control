"""System routes: health and info."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, Request

from backend import __version__
from backend.api.deps import CameraServiceDep, ConfigStoreDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.system import HealthOut, InfoOut
from backend.core.errors import NoTargetError
from backend.core.security import require_api_key
from backend.core.state import CameraState
from backend.services.locations import LocationService

router = APIRouter(tags=["system"])


@router.get("/health", operation_id="get_health", response_model=HealthOut)
async def get_health(camera: CameraServiceDep) -> HealthOut:
    """Open liveness probe. Always 200 while the server is up; 'degraded' on camera ERROR."""
    st = camera.status()
    return HealthOut(
        status="degraded" if st.state == CameraState.ERROR else "ok",
        camera_connected=st.connected,
        camera_state=st.state,
        version=__version__,
    )


def _free_bytes(storage: LocationService) -> int | None:
    try:
        return shutil.disk_usage(storage.root()).free
    except (OSError, NoTargetError):
        return None


@router.get(
    "/info",
    operation_id="get_info",
    response_model=InfoOut,
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)
async def get_info(request: Request, store: ConfigStoreDep) -> InfoOut:
    cfg = store.config
    return InfoOut(
        version=__version__,
        backend="demo" if cfg.demo_camera else "real",
        auth_enabled=cfg.api_key_hash is not None,
        output_free_bytes=_free_bytes(request.app.state.storage),
        ffmpeg_available=shutil.which("ffmpeg") is not None,
        started_at=request.app.state.started_at,
    )
