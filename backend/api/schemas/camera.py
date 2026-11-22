"""Schemas for the camera endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.core.state import CameraState


class CameraStatusOut(BaseModel):
    state: CameraState
    connected: bool
    model: str | None = None
    serial: str | None = None
    leased_by: str | None = Field(default=None, description="Owner of the exclusive lease, if any")
    last_error: str | None = None
    connected_at: datetime | None = None
    last_activity: datetime | None = Field(
        default=None, description="Last backend call (None if never connected)"
    )


class BatteryOut(BaseModel):
    level: str | None = Field(description="Raw camera value, e.g. '87%'; None if unavailable")
    percent: int | None = Field(description="Parsed percentage when the value is numeric")


class StorageCardOut(BaseModel):
    label: str
    base_dir: str
    capacity_kb: int
    free_kb: int
    free_images: int
    access: str


class StorageOut(BaseModel):
    cards: list[StorageCardOut]


class SummaryOut(BaseModel):
    summary: str
