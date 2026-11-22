"""Models for camera clock and capture-target routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CameraDateTimeOut(BaseModel):
    camera_time: datetime = Field(description="Camera clock (UTC epoch as the camera reports).")
    host_time: datetime = Field(description="Server clock when the camera was read.")
    offset_s: float = Field(description="camera_time - host_time in seconds.")


class CameraDateTimeIn(BaseModel):
    mode: Literal["host", "explicit"] = Field(
        description="host: set the camera to the server clock; explicit: set `time`."
    )
    time: datetime | None = Field(
        default=None, description="Required for explicit; a naive value is taken as UTC."
    )

    @model_validator(mode="after")
    def _check(self) -> CameraDateTimeIn:
        if self.mode == "explicit" and self.time is None:
            raise ValueError("time is required when mode is 'explicit'")
        if self.mode == "host" and self.time is not None:
            raise ValueError("time must be omitted when mode is 'host'")
        return self


class CaptureTargetOut(BaseModel):
    value: str | None = Field(description="Current raw choice, e.g. 'Memory card'.")
    choices: list[str]


class CaptureTargetIn(BaseModel):
    value: str = Field(
        min_length=1,
        max_length=64,
        description="'card', 'ram' or one of the camera's raw choices.",
    )
