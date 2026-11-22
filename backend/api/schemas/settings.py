"""Pydantic models for /settings."""

from __future__ import annotations

from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from backend.camera.backend import ConfigType

ValueIn = StrictBool | StrictInt | StrictFloat | StrictStr


class RangeOut(BaseModel):
    min: float
    max: float
    step: float


class SettingOut(BaseModel):
    name: str = Field(description="Camera widget name")
    alias: str | None = Field(default=None, description="Friendly alias accepted in URLs")
    label: str
    path: str
    type: ConfigType
    value: bool | int | float | str | None
    readonly: bool
    choices: list[str] = Field(default_factory=list)
    range: RangeOut | None = None
    writable: bool = Field(description="True if the generic settings API may change it")


class SettingValueIn(BaseModel):
    value: ValueIn = Field(description="New value; must match the widget type")


class SettingsPatchIn(BaseModel):
    values: dict[str, ValueIn] = Field(
        min_length=1, max_length=64, description="Setting name or alias -> new value"
    )


class SettingsPatchOut(BaseModel):
    results: list[SettingOut] = Field(description="Applied settings, in the order applied")
