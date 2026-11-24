"""Files on the camera card: browse, download, delete, download-all job."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from starlette.types import Receive, Scope, Send

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.camera_files import (
    CameraFileEntry,
    DownloadAllRequest,
    FolderListOut,
    FolderOut,
)
from backend.api.schemas.common import Ok, Page
from backend.api.schemas.files import binary_response
from backend.api.schemas.jobs import JobOut
from backend.core.security import require_api_key
from backend.services.camera_files import (
    CameraFilesService,
    join_camera_path,
    validate_camera_folder,
    validate_camera_name,
)

get_camera_files = service_dep(
    "camera_files",
    lambda s: CameraFilesService(s.camera_service, s.event_bus, s.job_manager, s.storage),
)
FilesDep = Annotated[CameraFilesService, Depends(get_camera_files)]


class _TempFileResponse(FileResponse):
    """FileResponse that always removes its temp dir, even if the client disconnects
    mid-stream (a plain BackgroundTask would not run then)."""

    def __init__(self, path: Path, tmp_dir: Path, **kwargs: Any) -> None:
        super().__init__(path, **kwargs)
        self._tmp_dir = tmp_dir

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)


# Separate router object, same prefix as the status router; paths do not clash.
router = APIRouter(
    prefix="/camera",
    tags=["camera-files"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get("/folders", operation_id="list_camera_folders", response_model=FolderListOut)
async def list_camera_folders(svc: FilesDep, folder: str = "/") -> FolderListOut:
    folder = validate_camera_folder(folder)
    names = await svc.list_folders(folder)
    return FolderListOut(
        folder=folder,
        folders=[FolderOut(name=n, path=join_camera_path(folder, n)) for n in names],
    )


@router.get("/files", operation_id="list_camera_files", response_model=Page[CameraFileEntry])
async def list_camera_files(
    svc: FilesDep,
    folder: str = "/",
    recursive: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> Page[CameraFileEntry]:
    folder = validate_camera_folder(folder)
    entries = await svc.list(folder, recursive)
    start = (page - 1) * limit
    return Page[CameraFileEntry](
        items=entries[start : start + limit], total=len(entries), page=page, limit=limit
    )


@router.post(
    "/files/download-all",
    operation_id="download_all_camera_files",
    response_model=JobOut,
    status_code=202,
)
async def download_all_camera_files(body: DownloadAllRequest, svc: FilesDep) -> JobOut:
    return JobOut.model_validate(svc.start_download_all(body).model_dump())


@router.get(
    "/files/{folder:path}/{name}",
    operation_id="download_camera_file",
    response_class=FileResponse,
    responses=binary_response("application/octet-stream", "The file from the card"),
)
async def download_camera_file(folder: str, name: str, svc: FilesDep) -> FileResponse:
    folder = validate_camera_folder("/" + folder)
    validate_camera_name(name)
    tmp_dir, path = await svc.fetch_to_temp(folder, name)
    return _TempFileResponse(
        path,
        tmp_dir,
        filename=name,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
    )


@router.delete("/files/{folder:path}/{name}", operation_id="delete_camera_file", response_model=Ok)
async def delete_camera_file(folder: str, name: str, svc: FilesDep) -> Ok:
    """Delete one file from the card. 409 while another owner holds the camera lease."""
    await svc.delete(validate_camera_folder("/" + folder), validate_camera_name(name))
    return Ok()
