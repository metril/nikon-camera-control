"""Schemas for the focus API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FocusRange(BaseModel):
    min: int = Field(description="Most negative accepted step count")
    max: int = Field(description="Most positive accepted step count")
    step: int = Field(ge=1, description="Step granularity")


class AutofocusResult(BaseModel):
    ok: Literal[True] = True
    focused: bool | None = Field(
        description="True when the camera reported a successful drive; null if unknown"
    )


class MfRequest(BaseModel):
    steps: int = Field(
        ge=-1_000_000,
        le=1_000_000,
        description="Signed motor steps (sign = direction); checked against the camera's range",
    )

    @field_validator("steps")
    @classmethod
    def _non_zero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("steps must be non-zero")
        return v


class MfResult(BaseModel):
    ok: Literal[True] = True
    steps: int
    relative_position: int = Field(description="Tracked position relative to the user-set origin")


class FocusStatus(BaseModel):
    relative_position: int
    range: FocusRange
    liveview_required: Literal[True] = True
    last_af_at: datetime | None = None


class FocusResetResult(BaseModel):
    ok: Literal[True] = True
    relative_position: int = 0


class StackRequest(BaseModel):
    steps_per_shot: int = Field(
        ge=1, le=32_767, description="Focus steps between shots (within the camera's drive range)"
    )
    shots: int = Field(ge=2, le=200)
    direction: Literal["near_to_far", "far_to_near"] = "near_to_far"
    settle_ms: int = Field(default=500, ge=0, le=60_000, description="Wait after each move")
    return_to_start: bool = True
    name: str | None = Field(default=None, max_length=40, description="Folder name suffix")
    filename_prefix: str | None = Field(
        default=None,
        max_length=40,
        description="Prefix for file names; unsafe characters become -. Defaults to the "
        "File name prefix setting",
    )


class AfPointRequest(BaseModel):
    x: float = Field(ge=0, le=1, description="Horizontal position in the frame (0 = left)")
    y: float = Field(ge=0, le=1, description="Vertical position in the frame (0 = top)")


class AfPointResult(BaseModel):
    ok: Literal[True] = True
    x: int = Field(description="Camera live view pixel X that was sent")
    y: int = Field(description="Camera live view pixel Y that was sent")
