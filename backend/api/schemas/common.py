"""Schemas shared by every endpoint: errors, pagination, events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Ok(BaseModel):
    ok: Literal[True] = True


class Page(BaseModel, Generic[T]):  # noqa: UP046 - explicit Generic keeps pydantic simple
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1, default=1)
    limit: int = Field(ge=1, default=50)


class EventType(StrEnum):
    CAMERA_STATE = "camera_state"
    CAMERA_CONNECTED = "camera_connected"
    CAMERA_DISCONNECTED = "camera_disconnected"
    SETTING_CHANGED = "setting_changed"
    BATTERY = "battery"
    CAPTURE_STARTED = "capture_started"
    CAPTURE_COMPLETE = "capture_complete"
    LIVEVIEW_STARTED = "liveview_started"
    LIVEVIEW_STOPPED = "liveview_stopped"
    TIMELAPSE_STARTED = "timelapse_started"
    TIMELAPSE_PAUSED = "timelapse_paused"
    TIMELAPSE_RESUMED = "timelapse_resumed"
    TIMELAPSE_STOPPED = "timelapse_stopped"
    TIMELAPSE_COMPLETED = "timelapse_completed"
    TIMELAPSE_FRAME = "timelapse_frame"
    TIMELAPSE_WARNING = "timelapse_warning"
    TIMELAPSE_ERROR = "timelapse_error"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    JOB_CREATED = "job_created"
    JOB_PROGRESS = "job_progress"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    CONFIG_CHANGED = "config_changed"
    ERROR = "error"


class Event(BaseModel):
    type: EventType
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)
