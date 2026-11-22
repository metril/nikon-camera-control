"""Camera state machine: states and the allowed transition table.

Any state may move to DISCONNECTED or ERROR (device lost / failure); that rule is
applied in ``can_transition`` rather than repeated in the table.
"""

from __future__ import annotations

from enum import StrEnum


class CameraState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    LIVEVIEW = "liveview"
    CAPTURING = "capturing"
    RECORDING = "recording"
    BULB = "bulb"
    BUSY = "busy"
    ERROR = "error"


S = CameraState

# Explicit (non-universal) transitions. Self transitions are not listed.
VALID_TRANSITIONS: dict[CameraState, frozenset[CameraState]] = {
    S.DISCONNECTED: frozenset({S.CONNECTING}),
    S.CONNECTING: frozenset({S.IDLE}),
    S.IDLE: frozenset({S.LIVEVIEW, S.CAPTURING, S.RECORDING, S.BULB, S.BUSY}),
    S.LIVEVIEW: frozenset({S.IDLE, S.CAPTURING, S.RECORDING, S.BUSY}),
    S.CAPTURING: frozenset({S.IDLE, S.LIVEVIEW}),
    S.RECORDING: frozenset({S.IDLE, S.LIVEVIEW}),
    S.BULB: frozenset({S.IDLE}),
    S.BUSY: frozenset({S.IDLE, S.LIVEVIEW}),
    S.ERROR: frozenset({S.IDLE, S.CONNECTING}),
}

UNIVERSAL_TARGETS: frozenset[CameraState] = frozenset({S.DISCONNECTED, S.ERROR})


def can_transition(from_state: CameraState, to_state: CameraState) -> bool:
    """True if moving from ``from_state`` to ``to_state`` is allowed (same state: False)."""
    if from_state == to_state:
        return False
    if to_state in UNIVERSAL_TARGETS:
        return True
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


def allowed_transitions(state: CameraState) -> frozenset[CameraState]:
    """All states reachable from ``state`` in one step."""
    return frozenset(s for s in CameraState if can_transition(state, s))
