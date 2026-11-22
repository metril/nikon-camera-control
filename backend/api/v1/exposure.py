"""Long exposure (bulb) and one-shot bracketed capture. Shares the /capture prefix with
``capture.py`` (which owns POST /capture and /capture/trigger); paths here are disjoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.exposure import BracketRequest, BulbRequest, BulbStatus
from backend.api.schemas.jobs import JobOut
from backend.api.v1.capture import build_capture_service
from backend.api.v1.files import build_file_service
from backend.api.v1.settings import build_settings_service
from backend.core.security import require_api_key
from backend.services.bracket_capture import BracketCaptureService
from backend.services.bulb import BulbService

router = APIRouter(
    prefix="/capture",
    tags=["capture"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def build_bulb_service(s: State) -> BulbService:
    files = s.services.get("files", lambda: build_file_service(s))
    return BulbService(
        s.camera_service,
        s.job_manager,
        s.event_bus,
        s.output_dir,
        files.index.invalidate,
        quiet_window_s=s.config_store.config.camera.event_quiet_window_s,
    )


def build_bracket_service(s: State) -> BracketCaptureService:
    settings = s.services.get("settings", lambda: build_settings_service(s))
    capture = s.services.get("capture", lambda: build_capture_service(s))
    return BracketCaptureService(
        s.camera_service, s.job_manager, s.event_bus, settings, capture, s.config_store
    )


get_bulb = service_dep("bulb", build_bulb_service)
get_bracket = service_dep("bracket_capture", build_bracket_service)
BulbDep = Annotated[BulbService, Depends(get_bulb)]
BracketDep = Annotated[BracketCaptureService, Depends(get_bracket)]


@router.post("/bulb", operation_id="start_bulb_capture", response_model=JobOut, status_code=202)
async def start_bulb_capture(body: BulbRequest, svc: BulbDep) -> JobOut:
    """Open the shutter for ``seconds`` (body must be in M mode). Returns the job; cancelling
    it closes the shutter at once and still keeps the frame."""
    return JobOut.model_validate((await svc.start(body)).model_dump())


@router.get("/bulb", operation_id="get_bulb_status", response_model=BulbStatus)
async def get_bulb_status(svc: BulbDep) -> BulbStatus:
    return svc.status()


@router.post(
    "/bracket", operation_id="start_bracket_capture", response_model=JobOut, status_code=202
)
async def start_bracket_capture(body: BracketRequest, svc: BracketDep) -> JobOut:
    """Capture one bracket set (every step applied and shot), then restore the settings."""
    return JobOut.model_validate((await svc.start(body)).model_dump())
