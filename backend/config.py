"""
Application Configuration

Uses Pydantic Settings for type-safe configuration from environment variables.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class CameraSettings(BaseSettings):
    """Camera-related configuration."""

    model_config = SettingsConfigDict(
        env_prefix="CAMERA_",
        case_sensitive=False,
    )

    # Connection
    usb_vendor_id: str = "0x04b0"  # Nikon
    connection_timeout: float = 10.0
    reconnect_interval: float = 2.0
    reconnect_max_retries: int = 5

    # Keep-alive (CRITICAL: D500 times out at 60 seconds)
    keepalive_interval: int = 30  # seconds
    keepalive_enabled: bool = True

    # Live View
    liveview_target_fps: int = 8  # Realistic for USB 2.0
    liveview_frame_timeout: float = 0.5  # 500ms per frame max
    liveview_quality: Literal["small", "medium", "large"] = "medium"

    # Capture
    capture_download_delay: float = 2.0  # Wait for camera to write to card
    capture_timeout: float = 30.0

    # Time-lapse
    timelapse_min_interval: float = 1.0  # 1 second minimum
    timelapse_max_duration: int = 86400  # 24 hours max


class MediaSettings(BaseSettings):
    """Media storage configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
    )

    output_path: Path = Path("/app/output")
    thumbnail_size: tuple[int, int] = (200, 200)
    max_concurrent_downloads: int = 2

    # FFmpeg settings for time-lapse
    ffmpeg_path: str = "ffmpeg"
    video_codec: str = "libx264"
    video_preset: str = "medium"
    video_crf: int = 23


class ServerSettings(BaseSettings):
    """Server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
    )

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"
    cors_origins: list[str] = ["*"]


class Settings(BaseSettings):
    """Combined application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    camera: CameraSettings = CameraSettings()
    media: MediaSettings = MediaSettings()
    server: ServerSettings = ServerSettings()


# Global settings instance
settings = Settings()
