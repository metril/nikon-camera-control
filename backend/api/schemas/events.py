"""Typed WebSocket event models (``/ws/events``).

Documentation only: the bus still carries ``Event`` with a dict payload. These models are what
the services publish, so the OpenAPI spec (and the generated client) can type each event;
``tests/api/test_event_models.py`` validates real published payloads against them.
Payloads carry counters and ids, never unbounded lists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.api.schemas.common import EventType
from backend.api.schemas.jobs import JobOut


class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class CameraStateData(_Payload):
    state: str
    previous: str | None = None
    connected: bool | None = Field(default=None, description="Only on the initial snapshot.")


class CameraConnectedData(_Payload):
    model: str | None = None
    serial: str | None = None


class CameraDisconnectedData(_Payload):
    reason: str = ""


class SettingChangedData(_Payload):
    name: str
    value: str | int | float | bool | None = None


class BatteryData(_Payload):
    level: int | float | str | None = None


class CameraFileRef(BaseModel):
    folder: str
    name: str


class CaptureStartedData(_Payload):
    bulb: bool | None = None
    seconds: float | None = None
    warnings: list[str] | None = None


class CaptureCompleteData(_Payload):
    files: list[CameraFileRef] = Field(default_factory=list)
    bulb: bool | None = None


class LiveviewStartedData(_Payload):
    pass


class LiveviewStoppedData(_Payload):
    frames: int = 0


class TimelapseData(_Payload):
    """Common counters on every time-lapse event; extras depend on the type."""

    session_id: str | None = None
    frames_done: int = 0
    sets_done: int = 0
    failures: int = 0
    planned_shots: int | None = Field(default=None, description="timelapse_started")
    reason: str | None = Field(default=None, description="timelapse_paused")
    interrupted: bool | None = Field(default=None, description="timelapse_stopped")
    error: str | None = Field(default=None, description="timelapse_error")
    index: int | None = Field(default=None, description="timelapse_frame")
    set_index: int | None = Field(default=None, description="timelapse_frame")
    step: int | None = Field(default=None, description="timelapse_frame")
    code: str | None = Field(default=None, description="timelapse_warning")
    message: str | None = Field(default=None, description="timelapse_warning")
    consecutive_failures: int | None = Field(default=None, description="timelapse_warning")


class RecordingStartedData(_Payload):
    max_seconds: int | None = None
    download_after: bool = False


class RecordedClip(BaseModel):
    folder: str
    name: str
    size: int = 0


class RecordingStoppedData(_Payload):
    reason: str
    duration_s: float = 0.0
    warning: str | None = None
    clips: list[RecordedClip] = Field(default_factory=list)
    job_id: str | None = None


class JobEventData(_Payload):
    job: JobOut


class ConfigChangedData(_Payload):
    config: dict[str, Any]
    restart_required: list[str] = Field(default_factory=list)


class PresetsChangedData(_Payload):
    action: str
    id: str | None = None
    kind: str | None = None


class ErrorData(_Payload):
    code: str
    message: str
    cause: str | None = None


class _EventBase(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CameraStateEvent(_EventBase):
    type: Literal[EventType.CAMERA_STATE] = EventType.CAMERA_STATE
    data: CameraStateData


class CameraConnectedEvent(_EventBase):
    type: Literal[EventType.CAMERA_CONNECTED] = EventType.CAMERA_CONNECTED
    data: CameraConnectedData


class CameraDisconnectedEvent(_EventBase):
    type: Literal[EventType.CAMERA_DISCONNECTED] = EventType.CAMERA_DISCONNECTED
    data: CameraDisconnectedData


class SettingChangedEvent(_EventBase):
    type: Literal[EventType.SETTING_CHANGED] = EventType.SETTING_CHANGED
    data: SettingChangedData


class BatteryEvent(_EventBase):
    type: Literal[EventType.BATTERY] = EventType.BATTERY
    data: BatteryData


class CaptureStartedEvent(_EventBase):
    type: Literal[EventType.CAPTURE_STARTED] = EventType.CAPTURE_STARTED
    data: CaptureStartedData


class CaptureCompleteEvent(_EventBase):
    type: Literal[EventType.CAPTURE_COMPLETE] = EventType.CAPTURE_COMPLETE
    data: CaptureCompleteData


class LiveviewStartedEvent(_EventBase):
    type: Literal[EventType.LIVEVIEW_STARTED] = EventType.LIVEVIEW_STARTED
    data: LiveviewStartedData


class LiveviewStoppedEvent(_EventBase):
    type: Literal[EventType.LIVEVIEW_STOPPED] = EventType.LIVEVIEW_STOPPED
    data: LiveviewStoppedData


class TimelapseStartedEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_STARTED] = EventType.TIMELAPSE_STARTED
    data: TimelapseData


class TimelapsePausedEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_PAUSED] = EventType.TIMELAPSE_PAUSED
    data: TimelapseData


class TimelapseResumedEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_RESUMED] = EventType.TIMELAPSE_RESUMED
    data: TimelapseData


class TimelapseStoppedEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_STOPPED] = EventType.TIMELAPSE_STOPPED
    data: TimelapseData


class TimelapseCompletedEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_COMPLETED] = EventType.TIMELAPSE_COMPLETED
    data: TimelapseData


class TimelapseFrameEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_FRAME] = EventType.TIMELAPSE_FRAME
    data: TimelapseData


class TimelapseWarningEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_WARNING] = EventType.TIMELAPSE_WARNING
    data: TimelapseData


class TimelapseErrorEvent(_EventBase):
    type: Literal[EventType.TIMELAPSE_ERROR] = EventType.TIMELAPSE_ERROR
    data: TimelapseData


class RecordingStartedEvent(_EventBase):
    type: Literal[EventType.RECORDING_STARTED] = EventType.RECORDING_STARTED
    data: RecordingStartedData


class RecordingStoppedEvent(_EventBase):
    type: Literal[EventType.RECORDING_STOPPED] = EventType.RECORDING_STOPPED
    data: RecordingStoppedData


class JobCreatedEvent(_EventBase):
    type: Literal[EventType.JOB_CREATED] = EventType.JOB_CREATED
    data: JobEventData


class JobProgressEvent(_EventBase):
    type: Literal[EventType.JOB_PROGRESS] = EventType.JOB_PROGRESS
    data: JobEventData


class JobCompletedEvent(_EventBase):
    type: Literal[EventType.JOB_COMPLETED] = EventType.JOB_COMPLETED
    data: JobEventData


class JobFailedEvent(_EventBase):
    type: Literal[EventType.JOB_FAILED] = EventType.JOB_FAILED
    data: JobEventData


class JobCancelledEvent(_EventBase):
    type: Literal[EventType.JOB_CANCELLED] = EventType.JOB_CANCELLED
    data: JobEventData


class ConfigChangedEvent(_EventBase):
    type: Literal[EventType.CONFIG_CHANGED] = EventType.CONFIG_CHANGED
    data: ConfigChangedData


class PresetsChangedEvent(_EventBase):
    type: Literal[EventType.PRESETS_CHANGED] = EventType.PRESETS_CHANGED
    data: PresetsChangedData


class ErrorEvent(_EventBase):
    type: Literal[EventType.ERROR] = EventType.ERROR
    data: ErrorData


TypedEvent = Annotated[
    CameraStateEvent
    | CameraConnectedEvent
    | CameraDisconnectedEvent
    | SettingChangedEvent
    | BatteryEvent
    | CaptureStartedEvent
    | CaptureCompleteEvent
    | LiveviewStartedEvent
    | LiveviewStoppedEvent
    | TimelapseStartedEvent
    | TimelapsePausedEvent
    | TimelapseResumedEvent
    | TimelapseStoppedEvent
    | TimelapseCompletedEvent
    | TimelapseFrameEvent
    | TimelapseWarningEvent
    | TimelapseErrorEvent
    | RecordingStartedEvent
    | RecordingStoppedEvent
    | JobCreatedEvent
    | JobProgressEvent
    | JobCompletedEvent
    | JobFailedEvent
    | JobCancelledEvent
    | ConfigChangedEvent
    | PresetsChangedEvent
    | ErrorEvent,
    Field(discriminator="type"),
]

EVENT_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.CAMERA_STATE: CameraStateEvent,
    EventType.CAMERA_CONNECTED: CameraConnectedEvent,
    EventType.CAMERA_DISCONNECTED: CameraDisconnectedEvent,
    EventType.SETTING_CHANGED: SettingChangedEvent,
    EventType.BATTERY: BatteryEvent,
    EventType.CAPTURE_STARTED: CaptureStartedEvent,
    EventType.CAPTURE_COMPLETE: CaptureCompleteEvent,
    EventType.LIVEVIEW_STARTED: LiveviewStartedEvent,
    EventType.LIVEVIEW_STOPPED: LiveviewStoppedEvent,
    EventType.TIMELAPSE_STARTED: TimelapseStartedEvent,
    EventType.TIMELAPSE_PAUSED: TimelapsePausedEvent,
    EventType.TIMELAPSE_RESUMED: TimelapseResumedEvent,
    EventType.TIMELAPSE_STOPPED: TimelapseStoppedEvent,
    EventType.TIMELAPSE_COMPLETED: TimelapseCompletedEvent,
    EventType.TIMELAPSE_FRAME: TimelapseFrameEvent,
    EventType.TIMELAPSE_WARNING: TimelapseWarningEvent,
    EventType.TIMELAPSE_ERROR: TimelapseErrorEvent,
    EventType.RECORDING_STARTED: RecordingStartedEvent,
    EventType.RECORDING_STOPPED: RecordingStoppedEvent,
    EventType.JOB_CREATED: JobCreatedEvent,
    EventType.JOB_PROGRESS: JobProgressEvent,
    EventType.JOB_COMPLETED: JobCompletedEvent,
    EventType.JOB_FAILED: JobFailedEvent,
    EventType.JOB_CANCELLED: JobCancelledEvent,
    EventType.CONFIG_CHANGED: ConfigChangedEvent,
    EventType.PRESETS_CHANGED: PresetsChangedEvent,
    EventType.ERROR: ErrorEvent,
}
