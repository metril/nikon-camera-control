"""Local output-directory files: list, download, delete, thumbnails."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok
from backend.api.schemas.files import (
    DeletePathsRequest,
    DeletePathsResult,
    FailedPath,
    FileEntry,
    FilePage,
    FolderEntry,
    ZipRequest,
    ZipTicket,
    binary_response,
)
from backend.core.security import require_api_key
from backend.services.files import FileService, KindFilter, SortOrder

# The ZIP download route is authorised by its single-use ticket (a plain browser navigation
# cannot send an API key), so it lives on the unauthenticated router; the rest is included below.
router = APIRouter(tags=["files"], responses=ERROR_RESPONSES)
_authed = APIRouter(prefix="/files", dependencies=[Depends(require_api_key)])


def build_file_service(s: State) -> FileService:
    return FileService(s.storage, lambda: s.config_store.config.media.thumbnail_size)


get_files = service_dep("files", build_file_service)
FilesDep = Annotated[FileService, Depends(get_files)]


@_authed.get("", operation_id="list_files", response_model=FilePage)
async def list_files(
    svc: FilesDep,
    folder: Annotated[str, Query(description="Folder relative to the output dir")] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    kind: KindFilter = "all",
    sort: SortOrder = "newest",
) -> FilePage:
    res = await svc.list(folder, page, limit, kind, sort)
    return FilePage(
        items=[
            FileEntry(
                path=f.path,
                name=f.name,
                folder=f.folder,
                size=f.size,
                modified=f.modified,
                kind=f.kind,
                has_thumbnail=f.has_thumbnail,
            )
            for f in res.items
        ],
        total=res.total,
        page=page,
        limit=limit,
        folders=[FolderEntry(path=d, name=d.rsplit("/", 1)[-1]) for d in res.folders],
    )


@_authed.post("/delete", operation_id="delete_files", response_model=DeletePathsResult)
async def delete_files(body: DeletePathsRequest, svc: FilesDep) -> DeletePathsResult:
    """Delete many files. Failures are reported per path; the others are still deleted."""
    deleted, failed = await svc.delete_many(body.paths)
    return DeletePathsResult(
        deleted=deleted, failed=[FailedPath(path=p, error=e) for p, e in failed]
    )


@_authed.post("/zip", operation_id="create_zip_download", response_model=ZipTicket)
async def create_zip_download(body: ZipRequest, svc: FilesDep, request: Request) -> ZipTicket:
    """Issue a single-use download URL (60 s). One path downloads the file itself, several
    stream a ZIP archive."""
    ticket = svc.create_zip_ticket(body.paths)
    return ZipTicket(url=request.url_for("download_zip", ticket=ticket).path)


@router.get(
    "/files/zip/{ticket}",
    operation_id="download_zip",
    name="download_zip",
    response_class=StreamingResponse,
    responses=binary_response("application/zip", "A ZIP archive, or the single file itself"),
)
async def download_zip(ticket: str, svc: FilesDep) -> Response:
    """Redeem a ticket from ``POST /files/zip``. No other credential is needed; a ticket
    works once."""
    plan = svc.redeem_zip_ticket(ticket)
    if plan.single is not None:
        return FileResponse(plan.single, filename=plan.single.name)
    return StreamingResponse(
        svc.stream_zip(plan.items),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="photos.zip"'},
    )


@_authed.get(
    "/{path:path}",
    operation_id="download_file",
    response_class=FileResponse,
    responses=binary_response("application/octet-stream", "The file content"),
)
async def download_file(path: str, svc: FilesDep) -> FileResponse:
    p = await asyncio.to_thread(svc.resolve_file, path)
    return FileResponse(p, filename=p.name)


@_authed.delete("/{path:path}", operation_id="delete_file", response_model=Ok)
async def delete_file(path: str, svc: FilesDep) -> Ok:
    await svc.delete(path)
    return Ok()


router.include_router(_authed)
