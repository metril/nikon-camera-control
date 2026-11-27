"""Schemas for files stored on the camera card."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.services.camera_files import validate_camera_folder, validate_camera_name

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


class CameraFileRef(BaseModel):
    folder: str
    name: str

    @field_validator("folder")
    @classmethod
    def _folder(cls, v: str) -> str:
        return validate_camera_folder(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_camera_name(v)


class DownloadAllRequest(BaseModel):
    file: CameraFileRef | None = Field(
        default=None, description="Download only this file (folder is then ignored)"
    )
    files: list[CameraFileRef] | None = Field(
        default=None,
        max_length=1000,
        description="Download only these files (folder and file are then ignored)",
    )
    folder: str | None = Field(
        default=None, description="Camera folder to download (recursively); null = whole card"
    )
    delete_after: bool = Field(default=False, description="Delete each file from the card after")
    only_new: bool = Field(default=True, description="Skip files already downloaded earlier")

    @field_validator("folder")
    @classmethod
    def _folder(cls, v: str | None) -> str | None:
        return None if v is None else validate_camera_folder(v)


class DeleteCameraFilesRequest(BaseModel):
    files: list[CameraFileRef] = Field(min_length=1, max_length=1000)


class CameraFileFailure(BaseModel):
    folder: str
    name: str
    error: str


class DeleteCameraFilesResult(BaseModel):
    deleted: list[CameraFileRef]
    failed: list[CameraFileFailure]
