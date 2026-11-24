"""Schemas for the system endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.core.state import CameraState


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"] = Field(description="'degraded' while the camera is in ERROR")
    camera_connected: bool
    camera_state: CameraState
    version: str


class InfoOut(BaseModel):
    version: str
    backend: Literal["real", "demo"] = Field(description="Camera backend kind in use")
    auth_enabled: bool
    output_free_bytes: int | None = Field(description="Free disk space of the output dir")
    ffmpeg_available: bool
    libgphoto2_version: str | None = Field(
        default=None, description="libgphoto2 version in use; none for the demo camera"
    )
    started_at: datetime = Field(
        description="UTC time this server process started; a change means it restarted"
    )
