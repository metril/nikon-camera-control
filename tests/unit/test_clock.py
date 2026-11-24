import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from backend.core import clock
from backend.services.sessions import _session_created


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    clock.set_zone(None)


def test_local_now_uses_configured_zone() -> None:
    clock.set_zone("Pacific/Kiritimati")  # UTC+14, no DST
    assert clock.local_now().utcoffset().total_seconds() == 14 * 3600  # type: ignore[union-attr]
    assert clock.utc_offset_minutes(1_800_000_000) == 840
    clock.set_zone(None)
    assert clock.utc_offset_minutes(1_800_000_000) is None


def test_stamp_follows_zone_and_sessions_parse_in_it() -> None:
    clock.set_zone("Pacific/Kiritimati")
    stamp = clock.local_now().strftime("%Y-%m-%d-%H%M%S")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d-\d{6}", stamp)
    created = _session_created(stamp + "-ab12")
    assert created.utcoffset().total_seconds() == 14 * 3600  # type: ignore[union-attr]
    assert abs((created - datetime.now(UTC)).total_seconds()) < 5
