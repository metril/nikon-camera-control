"""Live sync of settings changed on the camera body.

libgphoto2 reports a PTP DevicePropChanged as an UNKNOWN event whose text starts
``PTP Property <code> changed`` (see ``parse_property_event``). The backend hands the code to
``CameraService``, which feeds it here: codes are mapped to widget names, collected for
``DEBOUNCE_S``, then each widget is re-read through the normal settings path and announced as
SETTING_CHANGED. A widget is refreshed at most once per ``MIN_GAP_S`` and not at all within
``ECHO_S`` of the app's own write to it (the body echoes those).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from backend.api.schemas.common import EventType
from backend.camera.backend import ConfigType
from backend.core.errors import AppError

if TYPE_CHECKING:
    from backend.core.camera_service import CameraService

DEBOUNCE_S = 0.3
MIN_GAP_S = 0.5
ECHO_S = 1.5

# PTP device property code -> candidate widget names (first that exists is used). Standard PTP
# DevicePropCodes (PTP_DPC_* in libgphoto2 ptp.h); Nikon bodies use the standard codes for these.
PROP_WIDGETS: dict[int, tuple[str, ...]] = {
    0x5003: ("imagesize",),
    0x5004: ("imagequality",),
    0x5005: ("whitebalance",),
    0x5007: ("f-number",),
    0x500A: ("focusmode",),
    0x500B: ("exposuremetermode", "meteringmode"),
    0x500D: ("shutterspeed", "shutterspeed2"),
    0x500E: ("expprogram", "autoexposuremode"),
    0x500F: ("iso",),
    0x5010: ("exposurecompensation",),
}


class PropertySync:
    def __init__(self, camera: CameraService) -> None:
        self._camera = camera
        self._pending: dict[str, str | None] = {}  # widget -> latest reported value
        self._written: dict[str, float] = {}
        self._refreshed: dict[str, float] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def note_write(self, name: str) -> None:
        """The app just wrote ``name``: ignore the body's echo of it for ``ECHO_S``."""
        self._written[name] = time.monotonic()
        self._pending.pop(name, None)

    def on_codes(self, codes: list[int]) -> None:
        """Loop thread. Queue the widgets behind these property codes."""
        for code in codes:
            self.on_event(code)

    def on_event(self, code: int, name: str | None = None, value: str | None = None) -> None:
        """Loop thread. Queue one property change. The reported widget ``name`` wins over the
        code table; a reported ``value`` is applied directly when it fits the widget, else the
        widget is re-read."""
        # Only a name already known to exist: an unknown one would cost a full config read.
        found = self._camera.known_setting_name((name,)) if name else None
        if found is None:
            found = self._camera.known_setting_name(PROP_WIDGETS.get(code, ()))
            value = None if name else value  # a value for an unrecognised name is not ours
        if found is None:
            return
        if time.monotonic() - self._written.get(found, -ECHO_S) < ECHO_S:
            return
        self._pending[found] = value
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(DEBOUNCE_S, self._flush)

    def _flush(self) -> None:
        self._timer = None
        now = time.monotonic()
        due = [n for n in self._pending if now - self._refreshed.get(n, -MIN_GAP_S) >= MIN_GAP_S]
        values = {n: self._pending.pop(n) for n in due}
        if self._pending:  # rate-limited ones go again once their gap has passed
            wait = min(
                MIN_GAP_S - (now - self._refreshed[n])
                for n in self._pending
                if n in self._refreshed
            )
            self._timer = asyncio.get_running_loop().call_later(max(wait, 0.05), self._flush)
        for name in due:
            self._refreshed[name] = now
            raw = values[name]
            if raw is not None and self._apply(name, raw):
                continue
            task = asyncio.get_running_loop().create_task(self._refresh(name))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _apply(self, name: str, raw: str) -> bool:
        """Take the value the body reported without a re-read; False if it does not fit the
        cached widget (unknown choice, unparsable number)."""
        w = self._camera.cached_setting(name)
        if w is None:
            return False
        value: str | int | float | bool
        if w.type in (ConfigType.RADIO, ConfigType.MENU):
            if raw not in w.choices:
                return False
            value = raw
        elif w.type == ConfigType.TEXT:
            value = raw
        elif w.type == ConfigType.RANGE:
            try:
                value = float(raw)
            except ValueError:
                return False
        else:
            return False
        if w.value == value:
            return True
        self._camera.store_setting(replace(w, value=value))
        self._camera.bus.publish(EventType.SETTING_CHANGED, {"name": name, "value": value})
        return True

    async def _refresh(self, name: str) -> None:
        before = self._camera.cached_setting(name)
        try:
            w = await self._camera.refresh_setting(name)
        except (AppError, Exception):  # noqa: BLE001 - best effort; the next event retries
            return
        if time.monotonic() - self._written.get(name, -ECHO_S) < ECHO_S:
            return  # the app wrote it while we were reading
        if before is not None and before.value == w.value:
            return
        self._camera.bus.publish(EventType.SETTING_CHANGED, {"name": name, "value": w.value})

    def close(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._pending.clear()
        for t in list(self._tasks):
            t.cancel()
        with contextlib.suppress(Exception):
            self._tasks.clear()
