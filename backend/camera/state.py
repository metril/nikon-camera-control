"""
Camera State Management

Defines the state machine for camera operations.
The camera can only be in ONE state at a time to prevent conflicts.

State transitions:
    DISCONNECTED -> IDLE (on connect)
    IDLE -> LIVEVIEW (start live view)
    IDLE -> CAPTURING (trigger capture)
    LIVEVIEW -> IDLE (stop live view)
    LIVEVIEW -> CAPTURING (auto-stops live view, captures, auto-restarts)
    CAPTURING -> IDLE (capture complete)
    ANY -> DISCONNECTED (on disconnect/error)
"""

from enum import Enum, auto
from typing import Set


class CameraState(Enum):
    """Camera operation states - mutually exclusive."""

    DISCONNECTED = auto()  # Camera not connected
    IDLE = auto()          # Connected, ready for commands
    LIVEVIEW = auto()      # Live view streaming active
    CAPTURING = auto()     # Photo capture in progress
    RECORDING = auto()     # Video recording (future, deferred)
    BUSY = auto()          # Processing command, not ready for new ones
    ERROR = auto()         # Error state, needs recovery


# Valid state transitions
VALID_TRANSITIONS: dict[CameraState, Set[CameraState]] = {
    CameraState.DISCONNECTED: {CameraState.IDLE},
    CameraState.IDLE: {
        CameraState.LIVEVIEW,
        CameraState.CAPTURING,
        CameraState.DISCONNECTED,
        CameraState.BUSY,
    },
    CameraState.LIVEVIEW: {
        CameraState.IDLE,
        CameraState.CAPTURING,  # Auto-pauses live view
        CameraState.DISCONNECTED,
        CameraState.ERROR,
    },
    CameraState.CAPTURING: {
        CameraState.IDLE,
        CameraState.LIVEVIEW,  # Resume after capture
        CameraState.DISCONNECTED,
        CameraState.ERROR,
    },
    CameraState.RECORDING: {
        CameraState.IDLE,
        CameraState.DISCONNECTED,
        CameraState.ERROR,
    },
    CameraState.BUSY: {
        CameraState.IDLE,
        CameraState.LIVEVIEW,
        CameraState.DISCONNECTED,
        CameraState.ERROR,
    },
    CameraState.ERROR: {
        CameraState.IDLE,
        CameraState.DISCONNECTED,
    },
}


def can_transition(from_state: CameraState, to_state: CameraState) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, set())


def get_allowed_transitions(state: CameraState) -> Set[CameraState]:
    """Get all allowed transitions from the current state."""
    return VALID_TRANSITIONS.get(state, set())


# Human-readable state descriptions for UI
STATE_DESCRIPTIONS: dict[CameraState, str] = {
    CameraState.DISCONNECTED: "Camera not connected",
    CameraState.IDLE: "Ready",
    CameraState.LIVEVIEW: "Live View active",
    CameraState.CAPTURING: "Capturing photo...",
    CameraState.RECORDING: "Recording video...",
    CameraState.BUSY: "Processing...",
    CameraState.ERROR: "Error - check connection",
}
