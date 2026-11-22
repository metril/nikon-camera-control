"""Time-lapse session manifest (on-disk contract) and API response models.

On disk a session is ``<output_dir>/sessions/<id>/`` containing ``session.json`` (the manifest
header: everything except ``frames``) and ``frames.jsonl`` (one ``SessionFrame`` JSON per line).
``SessionManifest.frames`` is only populated when explicitly requested; API views never embed it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 1


class SessionStatus(StrEnum):
    CONFIGURED = "configured"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


ACTIVE_STATUSES = frozenset({SessionStatus.RUNNING, SessionStatus.PAUSED})


class SessionFile(BaseModel):
    path: str = Field(description="Path relative to the session folder (no '..', not absolute).")
    kind: Literal["raw", "jpeg", "other"] = "other"
    size: int = Field(default=0, ge=0, description="Size in bytes.")

    @field_validator("path")
    @classmethod
    def _relative(cls, v: str) -> str:
        parts = v.replace("\\", "/").split("/")
        if not v or v.startswith(("/", "\\")) or "\0" in v or ".." in parts or ":" in parts[0]:
            raise ValueError("path must be relative to the session folder")
        return v


class BracketInfo(BaseModel):
    step_index: int = Field(ge=0, description="Position of this shot inside its bracket set.")
    label: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class SessionFrame(BaseModel):
    index: int = Field(ge=0, description="0-based order of the frame within the session.")
    captured_at: datetime
    files: list[SessionFile] = Field(default_factory=list)
    bracket: BracketInfo | None = None
    set_index: int = Field(default=0, ge=0, description="Frames of one bracket set share it.")


class SessionVideo(BaseModel):
    name: str = Field(description="File name inside the session folder's videos/ directory.")
    created: datetime
    size: int = Field(default=0, ge=0)
    fps: float = Field(default=0, ge=0)
    codec: str = ""
    frames: int | None = Field(default=None, ge=0, description="Frames rendered, if recorded.")
    duration_s: float | None = Field(default=None, ge=0, description="Video length in seconds.")


class SessionManifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    id: str
    name: str
    created: datetime
    updated: datetime
    status: SessionStatus = SessionStatus.CONFIGURED
    config: dict[str, Any] = Field(default_factory=dict, description="Opaque; owned by the runner.")
    planned_frames: int = Field(default=0, ge=0)
    frames_captured: int = Field(default=0, ge=0)
    frames_failed: int = Field(default=0, ge=0)
    started: datetime | None = None
    finished: datetime | None = None
    error: str | None = None
    videos: list[SessionVideo] = Field(default_factory=list)
    frames: list[SessionFrame] = Field(default_factory=list, description="Empty unless loaded.")


class SessionSummary(BaseModel):
    """List view: counters only, never frames."""

    id: str
    name: str
    created: datetime
    updated: datetime
    status: SessionStatus
    planned_frames: int = 0
    frames_captured: int = 0
    frames_failed: int = 0
    started: datetime | None = None
    finished: datetime | None = None
    error: str | None = None
    video_count: int = 0
    corrupt: bool = Field(default=False, description="session.json is missing or unreadable.")


class SessionDetail(SessionSummary):
    schema_version: int = SCHEMA_VERSION
    config: dict[str, Any] = Field(default_factory=dict)
    videos: list[SessionVideo] = Field(default_factory=list)


class SessionRename(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="New session name.")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v
