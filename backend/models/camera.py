"""
Pydantic Models for Camera API

Data models for request/response validation.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Camera Status Models
# =============================================================================

class CameraState(str, Enum):
    """Camera operation states."""
    DISCONNECTED = "DISCONNECTED"
    IDLE = "IDLE"
    LIVEVIEW = "LIVEVIEW"
    CAPTURING = "CAPTURING"
    RECORDING = "RECORDING"
    BUSY = "BUSY"
    ERROR = "ERROR"


class CameraStatus(BaseModel):
    """Camera connection status response."""
    connected: bool
    state: CameraState
    state_description: str
    model: Optional[str] = None
    serial: Optional[str] = None
    last_activity: Optional[datetime] = None
    keepalive_enabled: bool = True


class CameraSummary(BaseModel):
    """Detailed camera information."""
    summary: str


# =============================================================================
# Settings Models
# =============================================================================

class SettingType(str, Enum):
    """Types of camera settings."""
    RADIO = "radio"
    MENU = "menu"
    TEXT = "text"
    RANGE = "range"
    TOGGLE = "toggle"
    DATE = "date"
    SECTION = "section"
    UNKNOWN = "unknown"


class SettingRange(BaseModel):
    """Range constraints for numeric settings."""
    min: float
    max: float
    step: Optional[float] = None


class CameraSetting(BaseModel):
    """Camera setting with current value and options."""
    name: str
    label: str
    path: str
    type: SettingType
    value: Any
    readonly: bool = False
    choices: Optional[list[str]] = None
    range: Optional[SettingRange] = None


class SettingsResponse(BaseModel):
    """Response containing multiple settings."""
    settings: dict[str, CameraSetting]
    count: int


class SetSettingRequest(BaseModel):
    """Request to change a camera setting."""
    value: Any = Field(..., description="New value for the setting")


class SetSettingResponse(BaseModel):
    """Response after changing a setting."""
    success: bool
    setting: CameraSetting
    message: Optional[str] = None


# =============================================================================
# Capture Models
# =============================================================================

class CaptureRequest(BaseModel):
    """Request to capture a photo."""
    download: bool = Field(True, description="Download file after capture")
    delete_from_camera: bool = Field(False, description="Delete from camera after download")


class CaptureResponse(BaseModel):
    """Response after capturing a photo."""
    success: bool
    filename: Optional[str] = None
    path: Optional[str] = None
    size: Optional[int] = None
    message: Optional[str] = None


# =============================================================================
# File Models
# =============================================================================

class CapturedFile(BaseModel):
    """Information about a captured file."""
    filename: str
    path: str
    size: int
    created: datetime
    thumbnail_url: Optional[str] = None


class FileListResponse(BaseModel):
    """Response containing list of captured files."""
    files: list[CapturedFile]
    total: int
    page: int = 1
    per_page: int = 50


# =============================================================================
# Time-lapse Models
# =============================================================================

class TimelapseConfig(BaseModel):
    """Configuration for time-lapse capture."""
    interval_seconds: float = Field(..., ge=1.0, description="Seconds between shots")
    total_frames: Optional[int] = Field(None, ge=1, description="Total number of frames")
    duration_seconds: Optional[int] = Field(None, ge=1, description="Total duration in seconds")
    output_folder: Optional[str] = Field(None, description="Custom output folder name")


class TimelapseStatus(BaseModel):
    """Current time-lapse status."""
    running: bool
    frames_captured: int = 0
    total_frames: Optional[int] = None
    elapsed_seconds: float = 0
    estimated_remaining_seconds: Optional[float] = None
    last_frame_path: Optional[str] = None
    output_folder: Optional[str] = None


class TimelapseStartResponse(BaseModel):
    """Response when starting a time-lapse."""
    success: bool
    session_id: str
    config: TimelapseConfig
    output_folder: str


class TimelapseStopResponse(BaseModel):
    """Response when stopping a time-lapse."""
    success: bool
    frames_captured: int
    output_folder: str


# =============================================================================
# Video Generation Models
# =============================================================================

class VideoGenerateRequest(BaseModel):
    """Request to generate video from frames."""
    input_folder: str
    output_filename: Optional[str] = None
    fps: int = Field(24, ge=1, le=60)
    codec: str = Field("libx264", description="Video codec (libx264, libx265, prores)")
    quality: int = Field(23, ge=0, le=51, description="CRF quality (lower is better)")


class VideoGenerateResponse(BaseModel):
    """Response after video generation."""
    success: bool
    output_path: Optional[str] = None
    duration_seconds: Optional[float] = None
    file_size: Optional[int] = None
    message: Optional[str] = None


# =============================================================================
# WebSocket Event Models
# =============================================================================

class WebSocketEvent(BaseModel):
    """Base model for WebSocket events."""
    type: str
    timestamp: datetime = Field(default_factory=datetime.now)


class CameraStateEvent(WebSocketEvent):
    """Camera state change event."""
    type: str = "camera_state"
    old_state: CameraState
    new_state: CameraState


class CaptureCompleteEvent(WebSocketEvent):
    """Capture completion event."""
    type: str = "capture_complete"
    success: bool
    file: Optional[CapturedFile] = None
    error: Optional[str] = None


class TimelapseProgressEvent(WebSocketEvent):
    """Time-lapse progress update event."""
    type: str = "timelapse_progress"
    frames_captured: int
    total_frames: Optional[int] = None
    elapsed_seconds: float
    estimated_remaining_seconds: Optional[float] = None


class ErrorEvent(WebSocketEvent):
    """Error notification event."""
    type: str = "error"
    error_type: str
    message: str
    recoverable: bool = True
