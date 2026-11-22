"""Camera clock and capture target (separate from /settings on purpose)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.camera_admin import (
    CameraDateTimeIn,
    CameraDateTimeOut,
    CaptureTargetIn,
    CaptureTargetOut,
)
from backend.core.security import require_api_key
from backend.services.camera_admin import CameraAdminService

get_camera_admin = service_dep(
    "camera_admin", lambda s: CameraAdminService(s.camera_service, s.event_bus)
)
Svc = Annotated[CameraAdminService, Depends(get_camera_admin)]

router = APIRouter(
    prefix="/camera",
    tags=["camera"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("/datetime", operation_id="get_camera_datetime", response_model=CameraDateTimeOut)
async def get_camera_datetime(svc: Svc) -> CameraDateTimeOut:
    """Camera clock, server clock and their offset."""
    return await svc.get_datetime()


@router.put("/datetime", operation_id="set_camera_datetime", response_model=CameraDateTimeOut)
async def set_camera_datetime(body: CameraDateTimeIn, svc: Svc) -> CameraDateTimeOut:
    """Set the camera clock to the server clock (`host`) or to `time` (`explicit`), showing
    wall-clock time in `utc_offset_minutes` (default: the server's local zone; pass the
    browser's offset to get the photographer's local time). Returns the clock read back.
    409 while another owner holds the camera."""
    return await svc.set_datetime(
        explicit=body.time if body.mode == "explicit" else None,
        utc_offset_minutes=body.utc_offset_minutes,
    )


@router.get("/capture-target", operation_id="get_capture_target", response_model=CaptureTargetOut)
async def get_capture_target(svc: Svc) -> CaptureTargetOut:
    return await svc.get_capture_target()


@router.put("/capture-target", operation_id="set_capture_target", response_model=CaptureTargetOut)
async def set_capture_target(body: CaptureTargetIn, svc: Svc) -> CaptureTargetOut:
    """`card`, `ram` or a raw choice. 409 during a recording or time-lapse."""
    return await svc.set_capture_target(body.value)
