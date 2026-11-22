"""Schemas for the capture API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.api.schemas.files import MediaKind


class CaptureRequest(BaseModel):
    download: bool = Field(default=True, description="Download the captured files to the server")
    delete_from_camera: bool = Field(
        default=False, description="Delete from the card after download (ignored if download=false)"
    )
    filename_prefix: str | None = Field(
        default=None, max_length=40, description="Prefix for file names; unsafe characters become _"
    )


class CapturedFile(BaseModel):
    name: str
    path: str = Field(description="Path relative to the output directory")
    size: int = Field(ge=0)
    kind: MediaKind


class CameraFileOut(BaseModel):
    folder: str
    name: str


class CaptureOut(BaseModel):
    files: list[CapturedFile] = Field(description="Downloaded files (empty if download=false)")
    camera_files: list[CameraFileOut] = Field(description="Files created on the camera card")
