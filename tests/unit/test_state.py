import pytest

from backend.core.state import CameraState as S
from backend.core.state import allowed_transitions, can_transition


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (S.DISCONNECTED, S.CONNECTING),
        (S.CONNECTING, S.IDLE),
        (S.IDLE, S.LIVEVIEW),
        (S.LIVEVIEW, S.IDLE),
        (S.IDLE, S.CAPTURING),
        (S.CAPTURING, S.IDLE),
        (S.LIVEVIEW, S.CAPTURING),
        (S.CAPTURING, S.LIVEVIEW),
        (S.IDLE, S.RECORDING),
        (S.RECORDING, S.IDLE),
        (S.LIVEVIEW, S.RECORDING),
        (S.RECORDING, S.LIVEVIEW),
        (S.IDLE, S.BULB),
        (S.BULB, S.IDLE),
        (S.ERROR, S.IDLE),
    ],
)
def test_allowed(a: S, b: S) -> None:
    assert can_transition(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (S.DISCONNECTED, S.IDLE),
        (S.DISCONNECTED, S.LIVEVIEW),
        (S.IDLE, S.IDLE),
        (S.CAPTURING, S.RECORDING),
        (S.BULB, S.LIVEVIEW),
        (S.ERROR, S.LIVEVIEW),
    ],
)
def test_disallowed(a: S, b: S) -> None:
    assert not can_transition(a, b)


@pytest.mark.parametrize("a", [s for s in S])
def test_any_to_disconnected_or_error(a: S) -> None:
    for target in (S.DISCONNECTED, S.ERROR):
        assert can_transition(a, target) == (a != target)


def test_allowed_transitions_matches_can_transition() -> None:
    for a in S:
        assert allowed_transitions(a) == {b for b in S if can_transition(a, b)}
