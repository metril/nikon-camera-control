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
from typing import TYPE_CHECKING

from backend.api.schemas.common import EventType
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
        self._pending: set[str] = set()
        self._written: dict[str, float] = {}
        self._refreshed: dict[str, float] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def note_write(self, name: str) -> None:
        """The app just wrote ``name``: ignore the body's echo of it for ``ECHO_S``."""
        self._written[name] = time.monotonic()
        self._pending.discard(name)

    def on_codes(self, codes: list[int]) -> None:
        """Loop thread. Queue the widgets behind these property codes."""
        now = time.monotonic()
        for code in codes:
            candidates = PROP_WIDGETS.get(code)
            if not candidates:
                continue
            # Only a name already known to exist: an unknown one would cost a full config read.
            name = self._camera.known_setting_name(candidates)
            if name is not None:
                if now - self._written.get(name, -ECHO_S) < ECHO_S:
                    continue
                self._pending.add(name)
        if self._pending and self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(DEBOUNCE_S, self._flush)

    def _flush(self) -> None:
        self._timer = None
        now = time.monotonic()
        due = [n for n in self._pending if now - self._refreshed.get(n, -MIN_GAP_S) >= MIN_GAP_S]
        self._pending.difference_update(due)
        if self._pending:  # rate-limited ones go again once their gap has passed
            wait = min(
                MIN_GAP_S - (now - self._refreshed[n])
                for n in self._pending
                if n in self._refreshed
            )
            self._timer = asyncio.get_running_loop().call_later(max(wait, 0.05), self._flush)
        for name in due:
            self._refreshed[name] = now
            task = asyncio.get_running_loop().create_task(self._refresh(name))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

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
