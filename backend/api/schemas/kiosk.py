"""Kiosk display schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class KioskDisplayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool = Field(description="True to wake the kiosk screen, false to let it sleep.")


class KioskDisplayOut(BaseModel):
    on: bool = Field(description="The recorded display state.")
