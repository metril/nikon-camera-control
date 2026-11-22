"""Schemas for the live view endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.core.state import CameraState


class LiveViewStatusOut(BaseModel):
    running: bool = Field(description="Producer task is running (stream wanted)")
    active: bool = Field(description="Frames are flowing right now")
    sticky: bool = Field(description="Started explicitly; survives the last client leaving")
    phase: Literal["stopped", "waiting", "streaming"]
    reason: str | None = Field(default=None, description="Why the stream is waiting, if it is")
    camera_state: CameraState
    fps: float = Field(description="Rolling produced frames per second")
    target_fps: int
    subscribers: int
    frames_produced: int
    frames_sent: int = Field(description="Frames delivered to clients (all subscribers)")
    frames_dropped: int = Field(description="Frames skipped by slow clients")
    last_frame_bytes: int | None = None
    last_frame_at: float | None = Field(default=None, description="Unix seconds")
    client_frames_sent: int | None = Field(default=None, description="This WebSocket client only")
    client_frames_dropped: int | None = Field(default=None, description="This client only")
