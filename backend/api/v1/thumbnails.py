"""Cached thumbnails of local files (separate from /files so file paths stay unambiguous)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.files import binary_response
from backend.api.v1.files import FilesDep
from backend.core.security import require_api_key

router = APIRouter(
    prefix="/thumbnails",
    tags=["files"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)


@router.get(
    "/{path:path}",
    operation_id="get_thumbnail",
    response_class=FileResponse,
    responses=binary_response("image/jpeg", "JPEG thumbnail"),
)
async def get_thumbnail(
    path: str,
    svc: FilesDep,
    size: Annotated[int | None, Query(ge=64, le=1024, description="Longest edge in px")] = None,
) -> FileResponse:
    """JPEG thumbnail of the file at ``path`` (relative to the output dir)."""
    thumb = await svc.thumbnails.get(svc.resolve_file(path), size)
    return FileResponse(
        thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )
