"""
Camera Exception Hierarchy

Comprehensive error handling for camera operations.
All exceptions inherit from CameraError for easy catching.
"""

from typing import Optional


class CameraError(Exception):
    """Base exception for all camera-related errors."""

    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable


# Connection Errors
class CameraConnectionError(CameraError):
    """Failed to connect to camera."""

    def __init__(self, message: str = "Failed to connect to camera"):
        super().__init__(message, recoverable=True)


class CameraNotFoundError(CameraConnectionError):
    """Camera not detected on USB bus."""

    def __init__(self, message: str = "No Nikon camera detected. Check USB connection."):
        super().__init__(message)


class CameraDisconnectedError(CameraError):
    """Camera disconnected during operation."""

    def __init__(self, message: str = "Camera disconnected unexpectedly"):
        super().__init__(message, recoverable=True)


class CameraTimeoutError(CameraError):
    """Camera operation timed out."""

    def __init__(
        self,
        operation: str,
        timeout_seconds: float,
        message: Optional[str] = None
    ):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        msg = message or f"Camera operation '{operation}' timed out after {timeout_seconds}s"
        super().__init__(msg, recoverable=True)


# State Errors
class CameraStateError(CameraError):
    """Invalid state for requested operation."""

    def __init__(
        self,
        operation: str,
        current_state: str,
        required_states: Optional[list[str]] = None
    ):
        self.operation = operation
        self.current_state = current_state
        self.required_states = required_states or []

        if required_states:
            states_str = ", ".join(required_states)
            message = f"Cannot {operation}: camera is {current_state}. Required state: {states_str}"
        else:
            message = f"Cannot {operation}: camera is {current_state}"

        super().__init__(message, recoverable=True)


class CameraBusyError(CameraStateError):
    """Camera is busy with another operation."""

    def __init__(self, current_operation: str):
        super().__init__(
            operation="execute command",
            current_state=f"busy ({current_operation})",
            required_states=["IDLE"]
        )


class LiveViewActiveError(CameraStateError):
    """Operation not allowed while live view is active."""

    def __init__(self, operation: str):
        super().__init__(
            operation=operation,
            current_state="LIVEVIEW",
            required_states=["IDLE"]
        )


# Settings Errors
class CameraSettingError(CameraError):
    """Error reading or writing camera setting."""

    def __init__(self, setting_name: str, reason: str):
        self.setting_name = setting_name
        self.reason = reason
        message = f"Setting '{setting_name}': {reason}"
        super().__init__(message, recoverable=True)


class SettingNotFoundError(CameraSettingError):
    """Setting does not exist on this camera."""

    def __init__(self, setting_name: str):
        super().__init__(setting_name, "setting not found on this camera")


class SettingReadOnlyError(CameraSettingError):
    """Setting is read-only and cannot be modified."""

    def __init__(self, setting_name: str, reason: Optional[str] = None):
        reason_str = reason or "read-only (may depend on camera mode dial setting)"
        super().__init__(setting_name, reason_str)


class SettingValueError(CameraSettingError):
    """Invalid value for setting."""

    def __init__(self, setting_name: str, value: str, valid_values: Optional[list[str]] = None):
        self.value = value
        self.valid_values = valid_values

        if valid_values:
            reason = f"'{value}' is not valid. Options: {', '.join(valid_values[:10])}"
            if len(valid_values) > 10:
                reason += f"... ({len(valid_values)} total)"
        else:
            reason = f"'{value}' is not a valid value"

        super().__init__(setting_name, reason)


# Capture Errors
class CaptureError(CameraError):
    """Error during photo/video capture."""

    def __init__(self, message: str = "Capture failed"):
        super().__init__(message, recoverable=True)


class CaptureAbortedError(CaptureError):
    """Capture was aborted (e.g., due to disconnect)."""

    def __init__(self, reason: str = "unknown"):
        super().__init__(f"Capture aborted: {reason}")


class FileTransferError(CameraError):
    """Error transferring file from camera."""

    def __init__(self, filename: str, reason: str):
        self.filename = filename
        self.reason = reason
        super().__init__(f"Failed to transfer '{filename}': {reason}", recoverable=True)


# Live View Errors
class LiveViewError(CameraError):
    """Error with live view operations."""

    def __init__(self, message: str = "Live view error"):
        super().__init__(message, recoverable=True)


class LiveViewTimeoutError(LiveViewError):
    """Live view frame timeout (camera may have timed out)."""

    def __init__(self):
        super().__init__(
            "Live view timeout. Camera may have auto-disconnected. "
            "Keep-alive mechanism may have failed."
        )


# USB Errors
class USBError(CameraError):
    """Low-level USB communication error."""

    def __init__(self, message: str):
        super().__init__(f"USB error: {message}", recoverable=False)
