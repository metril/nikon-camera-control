"""Domain exceptions shared by the camera backend, services and the API layer.

Every error carries a stable machine-readable ``code`` and an HTTP status so the
API error handler can render ``{"error": {"code", "message", "details"}}``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable error codes exposed in API responses."""

    INTERNAL_ERROR = "INTERNAL_ERROR"
    CAMERA_NOT_CONNECTED = "CAMERA_NOT_CONNECTED"
    CAMERA_NOT_FOUND = "CAMERA_NOT_FOUND"
    CAMERA_BUSY = "CAMERA_BUSY"
    CAMERA_TIMEOUT = "CAMERA_TIMEOUT"
    CAMERA_IO_ERROR = "CAMERA_IO_ERROR"
    CAMERA_OPERATION_FAILED = "CAMERA_OPERATION_FAILED"
    STORAGE_FULL = "STORAGE_FULL"
    INVALID_STATE = "INVALID_STATE"
    SETTING_NOT_FOUND = "SETTING_NOT_FOUND"
    SETTING_NOT_ALLOWED = "SETTING_NOT_ALLOWED"
    SETTING_INVALID = "SETTING_INVALID"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    PRESET_NOT_FOUND = "PRESET_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    CONFIG_INVALID = "CONFIG_INVALID"
    FEATURE_UNSUPPORTED = "FEATURE_UNSUPPORTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    FORBIDDEN = "FORBIDDEN"
    BULB_SHUTTER_OPEN = "BULB_SHUTTER_OPEN"


class AppError(Exception):
    """Base class. Subclasses set class-level ``code``/``http_status`` defaults."""

    code: str = ErrorCode.INTERNAL_ERROR
    http_status: int = 500
    recoverable: bool = True
    default_message: str = "Internal error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        recoverable: bool | None = None,
    ) -> None:
        self.message: str = message or self.default_message
        self.details: dict[str, Any] = dict(details or {})
        if recoverable is not None:
            self.recoverable = recoverable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }


class CameraNotConnected(AppError):
    code = ErrorCode.CAMERA_NOT_CONNECTED
    http_status = 503
    default_message = "Camera is not connected"


class CameraNotFound(AppError):
    code = ErrorCode.CAMERA_NOT_FOUND
    http_status = 404
    default_message = "No camera detected. Check the USB connection."


class CameraBusy(AppError):
    code = ErrorCode.CAMERA_BUSY
    http_status = 409
    default_message = "Camera is busy with another operation"


class CameraTimeout(AppError):
    code = ErrorCode.CAMERA_TIMEOUT
    http_status = 504
    default_message = "Camera operation timed out"


class CameraIOError(AppError):
    code = ErrorCode.CAMERA_IO_ERROR
    http_status = 502
    default_message = "Camera I/O error"


class CameraOperationFailed(AppError):
    """The camera rejected or failed one operation; the USB link itself is fine."""

    code = ErrorCode.CAMERA_OPERATION_FAILED
    http_status = 502
    recoverable = True
    default_message = "Camera operation failed"


class ShutterOpen(CameraOperationFailed):
    """A bulb exposure could not be closed: the shutter may still be open."""

    code = ErrorCode.BULB_SHUTTER_OPEN
    recoverable = False
    default_message = "Could not close the shutter"


class StorageFull(AppError):
    """No space left on the camera's storage card."""

    code = ErrorCode.STORAGE_FULL
    http_status = 507
    default_message = "Camera storage is full"


class InvalidState(AppError):
    code = ErrorCode.INVALID_STATE
    http_status = 409
    default_message = "Operation not allowed in the current state"


class SettingNotFound(AppError):
    code = ErrorCode.SETTING_NOT_FOUND
    http_status = 404
    default_message = "Setting not found"


class SettingNotAllowed(AppError):
    code = ErrorCode.SETTING_NOT_ALLOWED
    http_status = 403
    default_message = "Setting cannot be changed"


class SettingInvalid(AppError):
    code = ErrorCode.SETTING_INVALID
    http_status = 422
    default_message = "Invalid value for setting"


class FileNotFoundError_(AppError):  # noqa: N801
    """File missing (on camera or in the output directory)."""

    code = ErrorCode.FILE_NOT_FOUND
    http_status = 404
    default_message = "File not found"


class PathNotAllowed(AppError):
    code = ErrorCode.PATH_NOT_ALLOWED
    http_status = 400
    default_message = "Path is outside the allowed directory"


class JobNotFound(AppError):
    code = ErrorCode.JOB_NOT_FOUND
    http_status = 404
    default_message = "Job not found"


class PresetNotFound(AppError):
    code = ErrorCode.PRESET_NOT_FOUND
    http_status = 404
    default_message = "Preset not found"


class SessionNotFound(AppError):
    code = ErrorCode.SESSION_NOT_FOUND
    http_status = 404
    default_message = "Session not found"


class Forbidden(AppError):
    code = ErrorCode.FORBIDDEN
    http_status = 403
    default_message = "This operation is not allowed"


class Unauthorized(AppError):
    code = ErrorCode.UNAUTHORIZED
    http_status = 401
    default_message = "Missing or invalid API key"


class ConfigInvalid(AppError):
    code = ErrorCode.CONFIG_INVALID
    http_status = 422
    default_message = "Invalid configuration"


class FeatureUnsupported(AppError):
    code = ErrorCode.FEATURE_UNSUPPORTED
    http_status = 501
    default_message = "Feature not supported by this camera"


class UnsupportedMedia(AppError):
    code = ErrorCode.UNSUPPORTED_MEDIA
    http_status = 415
    default_message = "No thumbnail can be generated for this file type"
