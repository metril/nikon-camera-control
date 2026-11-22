"""Camera routes: status, connect/disconnect, battery, storage, summary."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from backend.api.deps import CameraServiceDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.camera import (
    BatteryOut,
    CameraStatusOut,
    StorageCardOut,
    StorageOut,
    SummaryOut,
)
from backend.core.camera_service import CameraService
from backend.core.errors import SettingNotFound
from backend.core.security import require_api_key

router = APIRouter(
    prefix="/camera",
    tags=["camera"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


async def _status(svc: CameraService) -> CameraStatusOut:
    st = svc.status()
    serial: str | None = None
    if st.connected:
        try:
            value = (await svc.get_setting("serialnumber")).value
            serial = None if value is None else str(value)
        except Exception:
            serial = None
    activity = getattr(svc, "_last_activity", 0.0)
    last_activity = (
        datetime.fromtimestamp(time.time() - (time.monotonic() - activity), UTC)
        if st.connected and activity
        else None
    )
    return CameraStatusOut(
        state=st.state,
        connected=st.connected,
        model=st.model,
        serial=serial,
        leased_by=st.leased_by,
        last_error=st.last_error,
        connected_at=(
            datetime.fromtimestamp(st.connected_at, UTC) if st.connected_at is not None else None
        ),
        last_activity=last_activity,
    )


@router.get("", operation_id="get_camera", response_model=CameraStatusOut)
async def get_camera(svc: CameraServiceDep) -> CameraStatusOut:
    return await _status(svc)


@router.post("/connect", operation_id="connect_camera", response_model=CameraStatusOut)
async def connect_camera(svc: CameraServiceDep) -> CameraStatusOut:
    await svc.connect()
    return await _status(svc)


@router.post("/disconnect", operation_id="disconnect_camera", response_model=CameraStatusOut)
async def disconnect_camera(svc: CameraServiceDep) -> CameraStatusOut:
    await svc.disconnect()
    return await _status(svc)


@router.get("/battery", operation_id="get_camera_battery", response_model=BatteryOut)
async def get_camera_battery(svc: CameraServiceDep) -> BatteryOut:
    try:
        value = (await svc.get_setting("batterylevel")).value
    except SettingNotFound:
        return BatteryOut(level=None, percent=None)
    level = None if value is None else str(value)
    m = re.match(r"\s*(\d{1,3})\s*%?\s*$", level or "")
    return BatteryOut(level=level, percent=int(m.group(1)) if m else None)


@router.get("/storage", operation_id="get_camera_storage", response_model=StorageOut)
async def get_camera_storage(svc: CameraServiceDep) -> StorageOut:
    cards = await svc.call(lambda b: b.storage_info())
    return StorageOut(
        cards=[
            StorageCardOut(
                label=c.label,
                base_dir=c.base_dir,
                capacity_kb=c.capacity_kb,
                free_kb=c.free_kb,
                free_images=c.free_images,
                access=c.access,
            )
            for c in cards
        ]
    )


@router.get("/summary", operation_id="get_camera_summary", response_model=SummaryOut)
async def get_camera_summary(svc: CameraServiceDep) -> SummaryOut:
    return SummaryOut(summary=await svc.call(lambda b: b.summary()))
