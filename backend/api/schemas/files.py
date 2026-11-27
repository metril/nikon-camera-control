"""Schemas for the local files API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.api.schemas.common import Page

MediaKind = Literal["image", "raw", "video", "other"]


class FileEntry(BaseModel):
    path: str = Field(description="Path relative to the output directory")
    name: str
    folder: str = Field(description="Parent folder relative to the output directory ('' = root)")
    size: int = Field(ge=0, description="Bytes")
    modified: float = Field(description="Unix seconds")
    kind: MediaKind
    has_thumbnail: bool


class FolderEntry(BaseModel):
    path: str
    name: str


class FilePage(Page[FileEntry]):
    folders: list[FolderEntry] = Field(
        default_factory=list, description="Immediate sub-folders of the requested folder"
    )


def binary_response(
    mime: str, description: str = "File content"
) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry declaring a 200 binary body (the generated client types it as Blob)."""
    return {
        200: {
            "description": description,
            "content": {mime: {"schema": {"type": "string", "format": "binary"}}},
        }
    }


class DeletePathsRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=5000, description="Paths to delete")


class FailedPath(BaseModel):
    path: str
    error: str


class DeletePathsResult(BaseModel):
    deleted: list[str]
    failed: list[FailedPath]


class ZipRequest(BaseModel):
    paths: list[str] = Field(
        min_length=1, max_length=5000, description="Files to download (one path = the file itself)"
    )


class ZipTicket(BaseModel):
    url: str = Field(description="Single-use download URL, valid for 60 seconds")
