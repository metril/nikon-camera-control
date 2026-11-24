"""CameraBackend protocol: the only surface the rest of the app uses to talk to a camera.

Contract:
- Fully synchronous and blocking. Only ever called from the CameraService worker
  thread, so implementations need no internal locking.
- Errors are raised as the domain exceptions in ``backend.core.errors``
  (CameraNotFound, CameraNotConnected, CameraTimeout, CameraIOError,
  SettingNotFound, SettingNotAllowed, SettingInvalid, FileNotFoundError_, ...).
  Raw gphoto2 errors must never escape.
  CameraIOError means the USB link is lost (the service tears the connection down);
  it must be raised ONLY for genuine link loss. A single failed operation (autofocus,
  rejected setting, ...) raises CameraOperationFailed; a full card raises StorageFull;
  an operation the body lacks raises FeatureUnsupported. All three leave the
  connection up.
- ``close()`` is idempotent and must not raise. ``open()`` after ``close()``
  re-initialises the device (used by the reset-after-timeout path).
- Config widget names are the leaf names gphoto2 reports (e.g. "iso", "shutterspeed",
  "capturetarget"); ``path`` is the full path (e.g. "/main/imgsettings/iso").
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class ConfigType(StrEnum):
    RADIO = "radio"
    MENU = "menu"
    TEXT = "text"
    RANGE = "range"
    TOGGLE = "toggle"
    DATE = "date"
    SECTION = "section"
    BUTTON = "button"
    UNKNOWN = "unknown"  # widget type the backend does not recognise; read-only


class FileKind(StrEnum):
    NORMAL = "normal"
    PREVIEW = "preview"  # embedded thumbnail/preview JPEG
    EXIF = "exif"


class EventType(StrEnum):
    FILE_ADDED = "file_added"
    FOLDER_ADDED = "folder_added"
    CAPTURE_COMPLETE = "capture_complete"
    TIMEOUT = "timeout"  # no event within the wait period
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ConfigRange:
    min: float
    max: float
    step: float


@dataclass(frozen=True, slots=True)
class ConfigWidget:
    """One config entry. Sections carry ``children``; leaves have ``children == ()``."""

    name: str
    label: str
    path: str
    type: ConfigType
    value: str | int | float | bool | None = None
    readonly: bool = False
    choices: tuple[str, ...] = ()
    range: ConfigRange | None = None
    children: tuple[ConfigWidget, ...] = ()


@dataclass(frozen=True, slots=True)
class CameraFilePath:
    folder: str  # e.g. "/store_00010001/DCIM/100NIKON"
    name: str  # e.g. "DSC_0001.NEF"


@dataclass(frozen=True, slots=True)
class CameraFileInfo:
    folder: str
    name: str
    size: int = 0
    mtime: float = 0.0  # unix seconds, 0 if unknown
    mime_type: str = ""
    width: int = 0
    height: int = 0


_PROP_EVENT = re.compile(r'PTP Property ([0-9a-fA-F]+) changed(?:, "([^"]*)"(?: to "(.*)"\s*$)?)?')


def parse_property_change(text: object) -> tuple[int, str | None, str | None] | None:
    """(PTP property code, widget name, new value) from a libgphoto2 ptp2 UNKNOWN event text, or
    None. Real bodies emit ``PTP Property 0000500f changed, "iso" to "800"`` (8 hex digits, the
    gphoto2 widget name, the new value); the bare ``PTP Property <hex> changed`` form has no
    name or value."""
    m = _PROP_EVENT.search(str(text))
    return (int(m.group(1), 16), m.group(2), m.group(3)) if m else None


def parse_property_event(text: object) -> int | None:
    """PTP device property code from a ptp2 UNKNOWN event text, else None."""
    ch = parse_property_change(text)
    return ch[0] if ch else None


@dataclass(frozen=True, slots=True)
class CameraEvent:
    type: EventType
    file: CameraFilePath | None = None  # set for FILE_ADDED
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StorageInfo:
    label: str
    base_dir: str
    capacity_kb: int = 0
    free_kb: int = 0
    free_images: int = 0
    access: str = ""  # "rw" | "ro" | ""


@runtime_checkable
class CameraBackend(Protocol):
    """Blocking camera driver."""

    # Called (on the worker thread) with the PTP code of each property-change event that
    # wait_for_event sees; set by the camera service.
    property_listener: Callable[[int, str | None, str | None], None] | None

    @property
    def is_open(self) -> bool:
        """True between a successful open() and close()."""
        ...

    def open(self) -> None:
        """Detect and initialise the camera. Raises CameraNotFound / CameraIOError."""
        ...

    def close(self) -> None:
        """Release the device. Idempotent, never raises."""
        ...

    def summary(self) -> str:
        """Human-readable camera summary; doubles as the cheapest liveness probe (keepalive)."""
        ...

    def model(self) -> str:
        """Camera model string (e.g. "Nikon DSC D500")."""
        ...

    def list_config(self) -> list[ConfigWidget]:
        """Full config tree: top-level sections with nested children."""
        ...

    def get_config(self, name: str) -> ConfigWidget:
        """One leaf widget by name. Raises SettingNotFound."""
        ...

    def set_config(self, name: str, value: str | int | float | bool) -> None:
        """Set one widget. Raises SettingNotFound, SettingNotAllowed (readonly), SettingInvalid."""
        ...

    def capture(self) -> CameraFilePath:
        """Capture an image (gp capture IMAGE) and return where it landed on the camera."""
        ...

    def trigger(self) -> None:
        """Fire the shutter without waiting (trigger_capture); result arrives via wait_for_event."""
        ...

    def capture_preview(self) -> bytes:
        """One live-view JPEG frame. Raises CameraTimeout / CameraIOError."""
        ...

    def end_preview(self) -> None:
        """Leave live view (viewfinder off, mirror down). Best effort: never raises for a
        missing/rejected widget; only genuine link loss may raise CameraIOError."""
        ...

    def invalidate_preview(self) -> None:
        """Forget that live view is on (no camera IO), so the next ``capture_preview``
        re-enables it. Called after captures, which may drop a D500 out of live view."""
        ...

    def wait_for_event(self, timeout_s: float) -> CameraEvent:
        """Block up to ``timeout_s`` for one event; returns type TIMEOUT if none arrives."""
        ...

    def list_folders(self, folder: str) -> list[str]:
        """Immediate sub-folder names (not paths) of ``folder``."""
        ...

    def list_files(self, folder: str) -> list[CameraFileInfo]:
        """Files directly in ``folder`` with info (size, mtime, mime)."""
        ...

    def list_file_names(self, folder: str) -> list[str]:
        """Names of the files directly in ``folder`` (cheap: no per-file info)."""
        ...

    def file_info(self, folder: str, name: str) -> CameraFileInfo:
        """Info for one file. Raises FileNotFoundError_."""
        ...

    def reset_device(self) -> None:
        """Best-effort USB-level reset of the camera device (may be called while closed).
        Never raises; used to un-wedge a body after a hung or failed call."""
        ...

    def read_file(self, folder: str, name: str, kind: FileKind, dest: Path) -> None:
        """Stream a camera file to ``dest`` (written to disk, never fully in memory).

        Raises FileNotFoundError_ if missing.
        """
        ...

    def delete_file(self, folder: str, name: str) -> None:
        """Delete a file from the camera. Raises FileNotFoundError_."""
        ...

    def storage_info(self) -> list[StorageInfo]:
        """One entry per storage card/slot."""
        ...
