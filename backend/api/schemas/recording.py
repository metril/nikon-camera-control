"""Schemas for in-camera video recording."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.core.state import CameraState


class RecordingStartRequest(BaseModel):
    max_seconds: int | None = Field(
        default=None,
        ge=1,
        le=1799,
        description="Stop automatically after this many seconds (default and maximum 1799, "
        "the D500's 29 min 59 s clip limit)",
    )
    download_after: bool = Field(
        default=False, description="After stopping, download the clip(s) into <output>/recordings/"
    )


class ClipOut(BaseModel):
    folder: str
    name: str
    size: int = Field(ge=0, description="Bytes on the card; 0 if unknown")


class RecordingStatus(BaseModel):
    active: bool
    started: datetime | None = Field(default=None, description="When the recording began")
    elapsed_s: float = Field(ge=0, description="Seconds recorded (final value once ended)")
    max_seconds: int | None = Field(default=None, description="Auto-stop limit of this recording")
    state: CameraState
    last_clip: ClipOut | None = None
    job_id: str | None = Field(default=None, description="Download job, if requested")
    ended_reason: str | None = Field(
        default=None,
        description="Why the last recording ended: user, max_seconds, camera_stopped, "
        "camera_disconnected, shutdown",
    )
    warning: str | None = Field(
        default=None, description="Problem noticed while recording/stopping"
    )
