"""Schemas for the config endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from backend.core.config_store import (
    AppConfig,
    CameraConfig,
    LiveViewConfig,
    MediaConfig,
    TimelapseConfig,
    VideoConfig,
)


class ConfigOut(BaseModel):
    """Public config; never contains the API key hash."""

    camera: CameraConfig
    liveview: LiveViewConfig
    timelapse: TimelapseConfig
    video: VideoConfig
    media: MediaConfig
    cors_origins: list[str]
    demo_camera: bool
    api_key_set: bool = Field(description="Whether an API key is configured")


class ConfigUpdateOut(BaseModel):
    config: ConfigOut
    restart_required: list[str] = Field(description="Changed fields that need an app restart")


class ConfigSchemaOut(BaseModel):
    """JSON schema of the public config, for rendering the settings form."""

    json_schema: dict[str, Any]


class ApiKeyOut(BaseModel):
    api_key: str = Field(description="Plaintext key; shown exactly once")
    config: ConfigOut


class ApiKeyDeletedOut(BaseModel):
    config: ConfigOut


def _opt(ann: Any) -> Any:
    return ann | None


def _optional_model(name: str, model: type[BaseModel], skip: frozenset[str] = frozenset()) -> Any:
    """All-optional mirror of ``model`` (constraints are enforced by the config store)."""
    fields: dict[str, Any] = {
        n: (_opt(f.annotation), Field(default=None, description=f.description))
        for n, f in model.model_fields.items()
        if n not in skip
    }
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


def _build_patch() -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for n, f in AppConfig.model_fields.items():
        if n == "api_key_hash":
            continue
        ann = f.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            sub = _optional_model(f"{ann.__name__}Patch", ann)
            fields[n] = (sub | None, Field(default=None, description=f.description))
        else:
            fields[n] = (_opt(ann), Field(default=None, description=f.description))
    return create_model("ConfigPatch", __config__=ConfigDict(extra="forbid"), **fields)


# Typed as Any for mypy; at runtime it is a pydantic model class (used as a body annotation).
ConfigPatch: Any = _build_patch()
