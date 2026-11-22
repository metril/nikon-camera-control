"""Video rendering request and video library entries."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

VideoCodec = Literal["h264", "h265", "prores", "vp9"]
VideoPreset = Literal[
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"
]
Resolution = Literal["source", "2160p", "1080p", "720p"]
Quality = Literal["low", "medium", "high"]


class RenderRequest(BaseModel):
    """Options for rendering a session's frames into a video. Omitted fields use ``video.*``
    from the app config."""

    fps: float | None = Field(default=None, ge=1, le=120, description="Output frame rate.")
    codec: VideoCodec | None = Field(
        default=None, description="h264, h265 (mp4), prores (mov) or vp9 (webm)."
    )
    crf: int | None = Field(
        default=None, ge=0, le=51, description="Constant rate factor (lower is better)."
    )
    quality: Quality | None = Field(
        default=None, description="Shortcut overriding crf (and the ProRes profile)."
    )
    preset: VideoPreset | None = Field(default=None, description="x264/x265 speed preset.")
    resolution: Resolution = Field(
        default="source", description="Fit inside this size, keeping aspect ratio."
    )
    bracket_frame: Literal["middle", "first", "last"] | int = Field(
        default="middle",
        description="Which shot of each bracket set to use: middle, first, last or a step index.",
    )
    deflicker: bool = Field(default=False, description="Apply ffmpeg's deflicker filter.")
    output_name: str | None = Field(
        default=None,
        max_length=120,
        description="File name (sanitised; extension is set by the codec; never overwrites).",
    )


class VideoEntry(BaseModel):
    session_id: str
    name: str
    path: str = Field(description="Path relative to the output directory.")
    size: int = Field(ge=0)
    created: datetime
    fps: float = 0
    codec: str = ""
    frames: int | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0, description="None for older videos.")
