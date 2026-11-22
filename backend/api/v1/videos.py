"""Render time-lapse videos and manage the rendered video library.

One router without a prefix: ``POST /sessions/{id}/video`` lives next to the sessions router's
paths (no clash: that router has no ``/video`` route) but auto-discovery only includes
``router``/``ws_router``, so full paths are declared here.
"""

from __future__ import annotations

import mimetypes
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok, Page
from backend.api.schemas.files import binary_response
from backend.api.schemas.jobs import JobOut
from backend.api.schemas.videos import RenderRequest, VideoEntry
from backend.api.v1.sessions import build_sessions_service
from backend.core.security import require_api_key
from backend.services.video import VideoService


def build_video_service(s: State) -> VideoService:
    sessions = s.services.get("sessions", lambda: build_sessions_service(s))
    return VideoService(s.config_store, sessions, s.job_manager, s.data_dir)


get_videos = service_dep("videos", build_video_service)
VideosDep = Annotated[VideoService, Depends(get_videos)]

router = APIRouter(
    tags=["videos"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.post(
    "/sessions/{session_id}/video",
    operation_id="render_session_video",
    response_model=JobOut,
    status_code=202,
)
async def render_session_video(session_id: str, body: RenderRequest, svc: VideosDep) -> JobOut:
    """Start rendering the session's frames (so far) into a video; returns the job."""
    return JobOut.model_validate((await svc.start(session_id, body)).model_dump())


@router.get("/videos", operation_id="list_videos", response_model=Page[VideoEntry])
async def list_videos(
    svc: VideosDep,
    session_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[VideoEntry]:
    items = await svc.list_videos(session_id)
    s = (page - 1) * limit
    return Page[VideoEntry](
        items=[VideoEntry(**e) for e in items[s : s + limit]],
        total=len(items),
        page=page,
        limit=limit,
    )


@router.get(
    "/videos/{session_id}/{name}",
    operation_id="download_video",
    response_class=FileResponse,
    responses=binary_response("video/*", "The video file"),
)
async def download_video(session_id: str, name: str, svc: VideosDep) -> FileResponse:
    """Stream the video; HTTP Range requests are supported."""
    path = await svc.video_path(session_id, name)
    return FileResponse(
        path,
        filename=name,
        content_disposition_type="inline",
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
    )


@router.delete("/videos/{session_id}/{name}", operation_id="delete_video", response_model=Ok)
async def delete_video(session_id: str, name: str, svc: VideosDep) -> Ok:
    await svc.delete_video(session_id, name)
    return Ok()
