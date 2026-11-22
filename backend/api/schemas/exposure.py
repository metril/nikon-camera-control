"""Bulb and one-shot bracket API models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.api.schemas.timelapse import Bracketing, NoBracketing, SettingValue

MAX_BULB_S = 3600.0


class BulbRequest(BaseModel):
    seconds: float = Field(ge=1, le=MAX_BULB_S, description="Exposure time in seconds.")
    download: bool = Field(default=True, description="Download the frame(s) to the output dir.")
    filename_prefix: str | None = Field(default=None, max_length=80)


class BulbStatus(BaseModel):
    active: bool
    job_id: str | None = None
    seconds: float | None = Field(default=None, description="Requested exposure time.")
    elapsed_s: float = Field(default=0.0, ge=0)
    remaining_s: float = Field(default=0.0, ge=0)


class BracketRequest(BaseModel):
    bracketing: Bracketing = Field(
        default_factory=NoBracketing,
        description="Same union as the time-lapse; must resolve to at least 2 steps.",
    )
    download: bool = Field(default=True, description="Download the frames to the output dir.")
    filename_prefix: str | None = Field(default=None, max_length=80)


class BracketShot(BaseModel):
    index: int
    label: str
    settings: dict[str, SettingValue]
    files: list[str] = Field(description="Paths relative to the output directory.")
    camera_files: list[str] = Field(default_factory=list)
