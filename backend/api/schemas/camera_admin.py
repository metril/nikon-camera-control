"""Models for camera clock and capture-target routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CameraDateTimeOut(BaseModel):
    camera_time: datetime = Field(
        description="The camera's raw epoch read as UTC. The camera stores wall-clock time with "
        "no zone and libgphoto2 converts it with the SERVER's zone, so this is only a true UTC "
        "instant if the camera was set from a UTC server; prefer camera_wall_time."
    )
    camera_epoch: int = Field(description="Raw epoch seconds as gphoto2 reports the clock.")
    camera_wall_time: datetime = Field(
        description="What the camera's clock face shows (no timezone): the raw epoch rendered "
        "in the server's zone."
    )
    host_time: datetime = Field(description="Server clock (UTC) when the camera was read.")
    host_utc_offset_minutes: int = Field(
        description="The server's UTC offset (minutes east) at that moment; `host` mode without "
        "an explicit offset sets the camera to the server's local wall time."
    )
    offset_s: float = Field(
        description="camera_epoch - server epoch in seconds: clock drift when the camera was "
        "set in `host` mode without an offset."
    )


class CameraDateTimeIn(BaseModel):
    mode: Literal["host", "explicit"] = Field(
        description="host: set the camera to the server clock; explicit: set `time`."
    )
    time: datetime | None = Field(
        default=None, description="Required for explicit; a naive value is taken as UTC."
    )
    utc_offset_minutes: int | None = Field(
        default=None,
        ge=-840,
        le=840,
        description="Minutes east of UTC of the wall-clock time the camera should show "
        "(browsers: -new Date().getTimezoneOffset()). Omitted: the server's local zone.",
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
