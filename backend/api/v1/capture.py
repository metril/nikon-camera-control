"""Capture routes: capture (+download) and trigger-only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.capture import CameraFileOut, CapturedFile, CaptureOut, CaptureRequest
from backend.api.schemas.common import Ok
from backend.api.v1.files import build_file_service
from backend.core.security import require_api_key
from backend.services.capture import CaptureService
from backend.services.storage import classify

router = APIRouter(
    prefix="/capture",
    tags=["capture"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def build_capture_service(s: State) -> CaptureService:
    files = s.services.get("files", lambda: build_file_service(s))
    cfg = s.config_store
    return CaptureService(
        s.camera_service,
        s.storage,
        files.index,
        keep_card_copy=lambda: cfg.config.camera.keep_card_copy,
        default_prefix=lambda: cfg.config.camera.filename_prefix,
    )


get_capture = service_dep("capture", build_capture_service)
CaptureDep = Annotated[CaptureService, Depends(get_capture)]


@router.post("", operation_id="capture_photo", response_model=CaptureOut)
async def capture_photo(body: CaptureRequest, svc: CaptureDep) -> CaptureOut:
    res = await svc.capture(
        download=body.download,
        delete_from_camera=body.delete_from_camera,
        filename_prefix=body.filename_prefix,
    )
    root = svc.output_dir
    return CaptureOut(
        files=[
            CapturedFile(
                name=p.name,
                path=p.resolve().relative_to(root.resolve()).as_posix(),
                size=p.stat().st_size,
                kind=classify(p.name),
            )
            for p in res.local
        ],
        camera_files=[CameraFileOut(folder=f.folder, name=f.name) for f in res.camera_files],
    )


@router.post("/trigger", operation_id="trigger_capture", response_model=Ok)
async def trigger_capture(svc: CaptureDep) -> Ok:
    await svc.trigger()
    return Ok()
