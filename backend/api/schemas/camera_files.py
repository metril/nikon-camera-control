"""Schemas for files stored on the camera card."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.services.camera_files import validate_camera_folder

CameraFileOrder = Literal["newest", "oldest", "name"]


class FolderOut(BaseModel):
    name: str
    path: str = Field(description="Absolute camera path of the sub-folder")


class FolderListOut(BaseModel):
    folder: str
    folders: list[FolderOut]


class CameraFileEntry(BaseModel):
    folder: str
    name: str
    size: int = Field(ge=0, description="Bytes")
    mtime: float = Field(description="Unix seconds, 0 if unknown")
    type: Literal["jpeg", "raw", "video", "other"]
    downloaded: bool = Field(description="Already in the download ledger (same size and mtime)")


class DownloadAllRequest(BaseModel):
    folder: str | None = Field(
        default=None, description="Camera folder to download (recursively); null = whole card"
    )
    delete_after: bool = Field(default=False, description="Delete each file from the card after")
    only_new: bool = Field(default=True, description="Skip files already downloaded earlier")

    @field_validator("folder")
    @classmethod
    def _folder(cls, v: str | None) -> str | None:
        return None if v is None else validate_camera_folder(v)
