"""Time-lapse routes: one typed config, status and run control."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.timelapse import (
    PresetList,
    TimelapseConfigResult,
    TimelapseSetup,
    TimelapseStatus,
)
from backend.api.v1.capture import build_capture_service
from backend.api.v1.sessions import build_sessions_service
from backend.api.v1.settings import build_settings_service
from backend.core.security import require_api_key
from backend.services.timelapse import TimelapseRunner
from backend.services.timelapse.brackets import PRESETS


def build_timelapse_service(s: State) -> TimelapseRunner:
    settings = s.services.get("settings", lambda: build_settings_service(s))
    capture = s.services.get("capture", lambda: build_capture_service(s))
    sessions = s.services.get("sessions", lambda: build_sessions_service(s))
    return TimelapseRunner(
        s.camera_service, settings, capture, sessions, s.event_bus, s.config_store
    )


get_timelapse = service_dep("timelapse", build_timelapse_service)
TimelapseDep = Annotated[TimelapseRunner, Depends(get_timelapse)]

router = APIRouter(
    prefix="/timelapse",
    tags=["timelapse"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("", operation_id="get_timelapse_status", response_model=TimelapseStatus)
async def get_timelapse_status(svc: TimelapseDep) -> TimelapseStatus:
    return svc.status()


@router.put("/config", operation_id="set_timelapse_config", response_model=TimelapseConfigResult)
async def set_timelapse_config(body: TimelapseSetup, svc: TimelapseDep) -> TimelapseConfigResult:
    return await svc.configure(body)


@router.get("/preview", operation_id="preview_timelapse", response_model=TimelapseConfigResult)
async def preview_timelapse(svc: TimelapseDep) -> TimelapseConfigResult:
    return svc.preview()


@router.get("/presets", operation_id="list_timelapse_presets", response_model=PresetList)
async def list_timelapse_presets() -> PresetList:
    return PresetList(items=list(PRESETS.values()))


@router.post("/start", operation_id="start_timelapse", response_model=TimelapseStatus)
async def start_timelapse(svc: TimelapseDep) -> TimelapseStatus:
    return await svc.start()


@router.post("/pause", operation_id="pause_timelapse", response_model=TimelapseStatus)
async def pause_timelapse(svc: TimelapseDep) -> TimelapseStatus:
    return await svc.pause()


@router.post("/resume", operation_id="resume_timelapse", response_model=TimelapseStatus)
async def resume_timelapse(svc: TimelapseDep) -> TimelapseStatus:
    return await svc.resume()


@router.post("/stop", operation_id="stop_timelapse", response_model=TimelapseStatus)
async def stop_timelapse(svc: TimelapseDep) -> TimelapseStatus:
    return await svc.stop()
