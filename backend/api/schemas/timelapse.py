"""Time-lapse API models: one typed config, status, estimate and presets."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SettingValue = str | int | float | bool

MIN_STEPS = 2
MAX_STEPS = 15


class TimelapseState(StrEnum):
    IDLE = "idle"
    CONFIGURED = "configured"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class BracketStep(BaseModel):
    settings: dict[str, SettingValue] = Field(
        min_length=1, description="Camera setting name (or alias) -> value for this shot."
    )
    label: str = Field(default="", max_length=80)
    delay_ms: int = Field(default=0, ge=0, le=60_000, description="Wait before this shot.")


class NoBracketing(BaseModel):
    mode: Literal["none"] = "none"


class StepsBracketing(BaseModel):
    mode: Literal["steps"] = "steps"
    steps: list[BracketStep] = Field(min_length=MIN_STEPS, max_length=MAX_STEPS)


class QuickBracketing(BaseModel):
    """Per-type value lists (a missing or empty list disables that type)."""

    mode: Literal["quick"] = "quick"
    exposure: list[str] | None = Field(default=None, max_length=MAX_STEPS)
    iso: list[str] | None = Field(default=None, max_length=MAX_STEPS)
    aperture: list[str] | None = Field(default=None, max_length=MAX_STEPS)
    shutter: list[str] | None = Field(default=None, max_length=MAX_STEPS)
    combine_mode: Literal["sequence", "paired"] = Field(
        default="sequence",
        description="sequence: every type adds its own shots; paired: values zipped by index.",
    )


class PresetBracketing(BaseModel):
    mode: Literal["preset"] = "preset"
    preset: str = Field(min_length=1, max_length=64, description="See GET /timelapse/presets.")


Bracketing = Annotated[
    NoBracketing | StepsBracketing | QuickBracketing | PresetBracketing,
    Field(discriminator="mode"),
]


class TimelapseSetup(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="Session name.")
    interval_s: float = Field(gt=0, le=86_400, description="Seconds between shot sets.")
    total_frames: int | None = Field(
        default=None, ge=1, le=100_000, description="Number of intervals (bracket sets)."
    )
    duration_s: int | None = Field(
        default=None, ge=1, description="Hard deadline for starting new sets."
    )
    bracketing: Bracketing = Field(default_factory=NoBracketing)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @model_validator(mode="after")
    def _exactly_one(self) -> TimelapseSetup:
        if (self.total_frames is None) == (self.duration_s is None):
            raise ValueError("give exactly one of total_frames or duration_s")
        return self


class ResolvedStep(BaseModel):
    index: int
    label: str
    settings: dict[str, SettingValue]
    delay_ms: int = 0


class Estimate(BaseModel):
    total_sets: int
    shots_per_set: int
    total_shots: int
    duration_s: float
    disk_bytes: int


class TimelapseConfigResult(BaseModel):
    config: TimelapseSetup
    resolved_steps: list[ResolvedStep] = Field(description="Empty without bracketing.")
    estimate: Estimate
    min_interval_s: float


class PresetOut(BaseModel):
    name: str
    description: str
    steps: list[BracketStep]


class PresetList(BaseModel):
    items: list[PresetOut]


class Counters(BaseModel):
    frames_done: int = 0
    frames_planned: int = 0
    sets_done: int = 0
    failures: int = 0
    consecutive_failures: int = 0


class Timing(BaseModel):
    started: datetime | None = None
    next_shot_at: datetime | None = None
    elapsed_s: float = 0.0
    eta_s: float | None = None


class LastFrame(BaseModel):
    index: int
    set_index: int
    files: list[str] = Field(description="File names of this frame only.")
    captured_at: datetime


class TimelapseStatus(BaseModel):
    state: TimelapseState
    session_id: str | None = None
    counters: Counters = Field(default_factory=Counters)
    timing: Timing = Field(default_factory=Timing)
    config: TimelapseSetup | None = None
    last_frame: LastFrame | None = None
    paused_reason: Literal["user", "camera_disconnected"] | None = None
    error: str | None = None
