"""Local output-directory files: list, download, delete, thumbnails."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from starlette.datastructures import State

from backend.api.deps import service_dep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok
from backend.api.schemas.files import FileEntry, FilePage, FolderEntry, binary_response
from backend.core.security import require_api_key
from backend.services.files import FileService, KindFilter, SortOrder

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


def build_file_service(s: State) -> FileService:
    return FileService(s.storage, lambda: s.config_store.config.media.thumbnail_size)


get_files = service_dep("files", build_file_service)
FilesDep = Annotated[FileService, Depends(get_files)]


@router.get("", operation_id="list_files", response_model=FilePage)
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


@router.get(
    "/{path:path}",
    operation_id="download_file",
    response_class=FileResponse,
    responses=binary_response("application/octet-stream", "The file content"),
)
async def download_file(path: str, svc: FilesDep) -> FileResponse:
    p = svc.resolve_file(path)
    return FileResponse(p, filename=p.name)


@router.delete("/{path:path}", operation_id="delete_file", response_model=Ok)
async def delete_file(path: str, svc: FilesDep) -> Ok:
    await svc.delete(path)
    return Ok()
