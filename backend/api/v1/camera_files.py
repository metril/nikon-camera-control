"""Files on the camera card: browse, download, delete, download-all job."""

from __future__ import annotations

import asyncio
import mimetypes
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.types import Receive, Scope, Send

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.camera_files import (
    CameraFileEntry,
    CameraFileFailure,
    CameraFileOrder,
    DeleteCameraFilesRequest,
    DeleteCameraFilesResult,
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
    order: CameraFileOrder = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> Page[CameraFileEntry]:
    folder = validate_camera_folder(folder)
    entries = await svc.list(folder, recursive, order)
    start = (page - 1) * limit
    return Page[CameraFileEntry](
        items=entries[start : start + limit], total=len(entries), page=page, limit=limit
    )


@router.get(
    "/thumbnail",
    operation_id="get_camera_thumbnail",
    response_class=Response,
    responses=binary_response("image/jpeg", "The camera's own preview JPEG of the file"),
)
async def get_camera_thumbnail(svc: FilesDep, folder: str, name: str) -> Response:
    data = await svc.fetch_preview(validate_camera_folder(folder), validate_camera_name(name))
    # short: the body reuses file names, so a long cache could show another photo
    headers = {"Cache-Control": "private, max-age=60"}
    return Response(data, media_type="image/jpeg", headers=headers)


@router.get(
    "/preview",
    operation_id="get_camera_preview",
    response_class=Response,
    responses=binary_response("image/jpeg", "Screen-sized JPEG (long edge 2560 px) of the file"),
)
async def get_camera_preview(
    request: Request,
    svc: FilesDep,
    folder: str,
    name: str,
    size: int | None = None,
    mtime: float | None = None,
) -> Response:
    """JPEG as rendered from the card file (RAW: its embedded preview); 415 for videos.

    ``size`` and ``mtime`` (from the listing) are cache-busters only: the body reuses file
    names. 409 while another owner holds the camera lease and the preview is not cached.
    A client that goes away cancels the render (a still-queued camera read never runs).
    """
    work = asyncio.ensure_future(
        svc.preview_file(validate_camera_folder(folder), validate_camera_name(name))
    )
    try:
        while not work.done():
            await asyncio.wait({work}, timeout=0.25)
            if not work.done() and await request.is_disconnected():
                work.cancel()
                return Response(status_code=499)
        path = work.result()
    finally:
        if not work.done():
            work.cancel()
    data = await asyncio.to_thread(path.read_bytes)
    # short: the body reuses file names, so a long cache could show another photo
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=60"})


@router.post(
    "/files/download-all",
    operation_id="download_all_camera_files",
    response_model=JobOut,
    status_code=202,
)
async def download_all_camera_files(body: DownloadAllRequest, svc: FilesDep) -> JobOut:
    return JobOut.model_validate(svc.start_download_all(body).model_dump())


@router.post(
    "/files/delete", operation_id="delete_camera_files", response_model=DeleteCameraFilesResult
)
async def delete_camera_files(
    body: DeleteCameraFilesRequest, svc: FilesDep
) -> DeleteCameraFilesResult:
    """Delete several files from the card. Failures (for example another owner holds the
    camera lease) are reported per file; the rest are still deleted."""
    deleted, failed = await svc.delete_many(body.files)
    return DeleteCameraFilesResult(
        deleted=deleted,
        failed=[CameraFileFailure(folder=r.folder, name=r.name, error=e) for r, e in failed],
    )


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
