"""In-camera video recording: start, stop, status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.recording import ClipOut, RecordingStartRequest, RecordingStatus
from backend.core.security import require_api_key
from backend.services.liveview import LiveViewService
from backend.services.recording import RecordingInfo, RecordingService

router = APIRouter(
    prefix="/recording",
    tags=["recording"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def build_recording_service(s: State) -> RecordingService:
    lv = s.services.get(
        "liveview", lambda: LiveViewService(s.camera_service, s.event_bus, s.config_store)
    )
    return RecordingService(
        s.camera_service,
        s.event_bus,
        s.job_manager,
        s.output_dir,
        liveview_running=lambda: lv.running,
    )


get_recording = service_dep("recording", build_recording_service)
RecordingDep = Annotated[RecordingService, Depends(get_recording)]


def _out(i: RecordingInfo) -> RecordingStatus:
    clip = (
        ClipOut(folder=i.last_clip[0].folder, name=i.last_clip[0].name, size=i.last_clip[1])
        if i.last_clip
        else None
    )
    return RecordingStatus(
        active=i.active,
        started=i.started,
        elapsed_s=round(i.elapsed_s, 2),
        max_seconds=i.max_seconds,
        state=i.state,
        last_clip=clip,
        job_id=i.job_id,
        ended_reason=i.reason,
        warning=i.warning,
        segments=i.segments,
        note=i.note,
    )


@router.get("", operation_id="get_recording", response_model=RecordingStatus)
async def get_recording_status(svc: RecordingDep) -> RecordingStatus:
    return _out(svc.info())


@router.post("/start", operation_id="start_recording", response_model=RecordingStatus)
async def start_recording(body: RecordingStartRequest, svc: RecordingDep) -> RecordingStatus:
    """Start recording a movie to the card. Holds the camera lease until stopped; live view
    is switched on if needed."""
    return _out(await svc.start(max_seconds=body.max_seconds, download_after=body.download_after))


@router.post("/stop", operation_id="stop_recording", response_model=RecordingStatus)
async def stop_recording(svc: RecordingDep) -> RecordingStatus:
    """Stop the recording; returns the clip and the download job id, if requested."""
    return _out(await svc.stop())
