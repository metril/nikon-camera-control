"""Preset API models: settings presets and bracket presets share one list."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator

from backend.api.schemas.settings import ValueIn
from backend.api.schemas.timelapse import (
    PresetBracketing,
    QuickBracketing,
    ResolvedStep,
    StepsBracketing,
)

ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SCHEMA_VERSION = 1

# A stored/builtin bracket preset always names real work ("none" is not a preset).
PresetBracketingIn = Annotated[
    StepsBracketing | QuickBracketing | PresetBracketing, Field(discriminator="mode")
]


class _PresetBase(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Unique per kind.")
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class SettingsPresetIn(_PresetBase):
    kind: Literal["settings"] = "settings"
    values: dict[str, ValueIn] = Field(
        min_length=1,
        max_length=40,
        description="Camera setting name (or alias) -> value, e.g. {'iso': 3200}.",
    )


class BracketPresetIn(_PresetBase):
    kind: Literal["bracket"] = "bracket"
    bracketing: PresetBracketingIn


PresetIn = Annotated[SettingsPresetIn | BracketPresetIn, Field(discriminator="kind")]


class SettingsPreset(SettingsPresetIn):
    id: str = Field(pattern=ID_PATTERN)
    builtin: bool = False
    created: datetime | None = None
    updated: datetime | None = None


class BracketPreset(BracketPresetIn):
    id: str = Field(pattern=ID_PATTERN)
    builtin: bool = Field(default=False, description="Built-in presets are read-only.")
    created: datetime | None = None
    updated: datetime | None = None


Preset = Annotated[SettingsPreset | BracketPreset, Field(discriminator="kind")]


class PresetItem(RootModel[Preset]):
    """One preset (SettingsPreset or BracketPreset, discriminated on `kind`)."""


class PresetCollection(BaseModel):
    items: list[Preset]
    warning: str | None = Field(
        default=None,
        description="Set when the presets file was corrupt (moved aside) or had skipped items.",
    )


class AppliedSetting(BaseModel):
    name: str
    value: str | int | float | bool | None = Field(description="Value read back from the camera.")


class ApplyResult(BaseModel):
    kind: Literal["settings", "bracket"]
    preset_id: str
    applied: list[AppliedSetting] = Field(
        default_factory=list, description="Settings preset: what the camera now reports."
    )
    steps: list[ResolvedStep] = Field(
        default_factory=list,
        description="Bracket preset: steps resolved against the camera (nothing was started).",
    )


class FromCameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    names: list[str] | None = Field(
        default=None,
        max_length=40,
        description="Setting names to capture; null = the common writable settings.",
    )


class PresetExport(BaseModel):
    schema_version: int = SCHEMA_VERSION
    exported: datetime
    presets: list[Preset] = Field(description="User presets only (built-ins are not exported).")


class PresetImportIn(BaseModel):
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1, le=SCHEMA_VERSION)
    replace: bool = Field(
        default=False,
        description="true: replace ALL user presets with the valid imported ones. "
        "false: merge; a name that already exists is skipped.",
    )
    presets: list[dict[str, Any]] = Field(max_length=500)


class ImportItemResult(BaseModel):
    index: int
    name: str | None = None
    id: str | None = None
    status: Literal["created", "skipped", "error"]
    error: str | None = None


class PresetImportResult(BaseModel):
    created: int
    skipped: int
    failed: int
    items: list[ImportItemResult]
