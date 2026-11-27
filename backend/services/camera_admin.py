"""Camera clock and capture target (both are kept out of the generic settings allowlist).

D500-UNVERIFIED assumptions are marked ``D500?``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from backend.api.schemas.camera_admin import CameraDateTimeOut, CaptureTargetOut
from backend.api.schemas.common import EventType
from backend.camera.backend import CameraBackend, ConfigType, ConfigWidget
from backend.core import clock as app_clock
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import (
    FeatureUnsupported,
    InvalidState,
    SettingInvalid,
    SettingNotFound,
)
from backend.core.events import EventBus
from backend.core.state import CameraState

# D500?: the clock widget is "datetime" (epoch int). "datetimeutc" is tried only when the
# former is missing. See the zone note at "date / time" below.
CLOCK_WIDGETS = ("datetime", "datetimeutc")
TARGET_WIDGET = "capturetarget"
_BUSY_STATES = frozenset({CameraState.RECORDING, CameraState.BULB, CameraState.CAPTURING})


def _clock_widget(b: CameraBackend) -> ConfigWidget:
    for name in CLOCK_WIDGETS:
        try:
            w = b.get_config(name)
        except SettingNotFound:
            continue
        if w.type is ConfigType.DATE and not w.readonly:
            return w
    raise FeatureUnsupported("This camera does not expose a settable clock")


def match_target(value: str, choices: tuple[str, ...]) -> str:
    """Friendly 'card'/'ram' or a raw choice (exact, then case-insensitive) -> camera choice."""
    low = value.strip().lower()
    hints = {"card": "card", "sd": "card", "ram": "ram", "internal": "ram"}
    found = [c for c in choices if c.lower() == low]
    if not found and low in hints:
        found = [c for c in choices if hints[low] in c.lower()]
    if len(found) != 1:
        raise SettingInvalid(
            f"Invalid capture target {value!r}",
            details={"name": TARGET_WIDGET, "value": value, "choices": list(choices)},
        )
    return found[0]


def _target_out(w: ConfigWidget) -> CaptureTargetOut:
    value = None if w.value is None else str(w.value)
    return CaptureTargetOut(value=value, choices=list(w.choices))


class CameraAdminService:
    def __init__(
        self,
        camera: CameraService,
        bus: EventBus | None = None,
        *,
        clock: Callable[[], float] = time.time,
        local_offset_s: Callable[[float], float] = lambda t: (
            datetime.fromtimestamp(t).astimezone().utcoffset() or timedelta(0)
        ).total_seconds(),
    ) -> None:
        """``clock`` (epoch seconds) and ``local_offset_s`` (server zone's UTC offset in seconds
        at an epoch) are injectable for tests."""
        self._cam = camera
        self._bus = bus
        self._clock = clock
        self._local_offset_s = local_offset_s

    # date / time ------------------------------------------------------------------------
    # D500-UNVERIFIED: libgphoto2's Nikon driver reads/writes the clock as wall-clock fields
    # converted with the SERVER's local zone, so the raw epoch E satisfies
    # fields(E in server zone) == what the camera shows. To show wall time W, write
    # E = W interpreted in the server zone.
    def _offset(self, epoch: float) -> int:
        return int(self._local_offset_s(epoch))

    def _raw_epoch_for(self, instant: float, utc_offset_s: int | None) -> int:
        """Raw epoch to write so the camera shows ``instant`` in the zone ``utc_offset_s``
        (None: the server's own zone, i.e. the raw epoch is the instant itself)."""
        if utc_offset_s is None:
            return int(round(instant))
        wall = round(instant) + utc_offset_s  # the clock face as seconds-since-epoch fields
        guess = wall - self._offset(wall - self._offset(instant))
        return int(wall - self._offset(guess))

    def _out(self, epoch: int | float, host: float) -> CameraDateTimeOut:
        off = self._offset(epoch)
        wall = datetime.fromtimestamp(epoch + off, UTC).replace(tzinfo=None)
        return CameraDateTimeOut(
            camera_time=datetime.fromtimestamp(epoch, UTC),
            camera_epoch=int(epoch),
            camera_wall_time=wall,
            host_time=datetime.fromtimestamp(host, UTC),
            host_utc_offset_minutes=round(self._offset(host) / 60),
            app_utc_offset_minutes=app_clock.utc_offset_minutes(host),
            offset_s=round(epoch - host, 3),
        )

    async def get_datetime(self) -> CameraDateTimeOut:
        def read(b: CameraBackend) -> CameraDateTimeOut:
            w = _clock_widget(b)
            return self._out(float(w.value or 0), self._clock())

        # KEEPALIVE priority: readable while a time-lapse holds the lease.
        return await self._cam.call(read, priority=Priority.KEEPALIVE)

    async def set_datetime(
        self, *, explicit: datetime | None = None, utc_offset_minutes: int | None = None
    ) -> CameraDateTimeOut:
        """Set the clock to ``explicit`` (an instant; naive = UTC) or, when None, to the host
        clock sampled at the write, showing wall time in ``utc_offset_minutes`` east of UTC
        (None: the app time zone, else the server's local zone)."""
        fixed: float | None = None
        if explicit is not None:
            if explicit.tzinfo is None:
                explicit = explicit.replace(tzinfo=UTC)
            fixed = explicit.timestamp()
        if utc_offset_minutes is None:  # default: the configured app zone, else the server's
            utc_offset_minutes = app_clock.utc_offset_minutes(
                fixed if fixed is not None else self._clock()
            )
        off = None if utc_offset_minutes is None else utc_offset_minutes * 60

        def write(b: CameraBackend) -> CameraDateTimeOut:
            w = _clock_widget(b)
            # D500 (verified on hardware): the clock write is refused ("Bad parameters" /
            # 0x200f Access Denied) while live view is on, so leave live view first. The
            # backend forgets the viewfinder flag, so the next preview frame re-enables it.
            b.end_preview()
            instant = fixed if fixed is not None else self._clock()
            b.set_config(w.name, self._raw_epoch_for(instant, off))
            return self._out(float(b.get_config(w.name).value or 0), self._clock())

        out = await self._cam.call(write)
        self._cam.invalidate_settings()
        return out

    # capture target ---------------------------------------------------------------------
    @staticmethod
    def _target(b: CameraBackend) -> ConfigWidget:
        return b.get_config(TARGET_WIDGET)

    async def get_capture_target(self) -> CaptureTargetOut:
        w = await self._cam.call(self._target, priority=Priority.KEEPALIVE)
        return CaptureTargetOut(
            value=None if w.value is None else str(w.value), choices=list(w.choices)
        )

    async def set_capture_target(self, value: str) -> CaptureTargetOut:
        st = self._cam.status()
        if st.leased_by is not None or st.state in _BUSY_STATES:
            raise InvalidState(
                "Capture target cannot change during a recording or time-lapse",
                details={"leased_by": st.leased_by, "state": str(st.state)},
            )

        def write(b: CameraBackend) -> ConfigWidget:
            w = self._target(b)
            if w.readonly:
                raise FeatureUnsupported("Capture target is read-only on this camera")
            b.set_config(TARGET_WIDGET, match_target(value, w.choices))
            return self._target(b)

        w = await self._cam.call(write)
        self._cam.invalidate_settings()
        if self._bus is not None:
            self._bus.publish(EventType.SETTING_CHANGED, {"name": TARGET_WIDGET, "value": w.value})
        return CaptureTargetOut(
            value=None if w.value is None else str(w.value), choices=list(w.choices)
        )
