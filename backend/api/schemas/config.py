"""Schemas for the config endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.core.config_store import (
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
