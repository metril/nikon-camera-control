"""App time zone: one process-wide setting (``AppConfig.timezone``) used for every
human-facing stamp (file, session and bracket names) and for the camera clock.
None means the server's local zone."""

from __future__ import annotations

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_zone: ZoneInfo | None = None


def validate_zone(name: str) -> str:
    """Return ``name`` if it is a known IANA zone, else raise ValueError."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"unknown time zone {name!r}") from exc
    return name


def set_zone(name: str | None) -> None:
    global _zone
    _zone = ZoneInfo(name) if name else None


def app_zone() -> ZoneInfo | None:
    return _zone


def local_now() -> datetime:
    """Current wall-clock time in the configured zone (server local zone when unset)."""
    return datetime.now(_zone)


def local_tz() -> tzinfo | None:
    """Zone to interpret generated names in (None: naive/server-local)."""
    return _zone


def utc_offset_minutes(epoch: float) -> int | None:
    """The configured zone's UTC offset (minutes east) at ``epoch``; None when unset."""
    if _zone is None:
        return None
    off = datetime.fromtimestamp(epoch, _zone).utcoffset()
    return round(off.total_seconds() / 60) if off is not None else None
