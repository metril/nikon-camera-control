"""Detect a Nikon camera that is plugged in but whose USB node this process cannot open."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NIKON_VENDOR_ID = "04b0"
DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")
DEFAULT_DEV_ROOT = Path("/dev/bus/usb")


@dataclass(frozen=True)
class UsbAccessProblem:
    bus: int
    device: int
    path: str
    product: str

    def details(self) -> dict[str, Any]:
        return {
            "bus": self.bus,
            "device": self.device,
            "path": self.path,
            "product": self.product,
            "hints": [
                f"Give the app read and write access to {self.path}.",
                "Add a udev rule for Nikon (vendor 04b0) that grants your user or group access, "
                "then replug the camera.",
                "In Docker, bind-mount /dev/bus/usb and run the container as a user in the "
                "device's group (group_add).",
            ],
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def find_unopenable_nikon(
    sysfs_root: Path = DEFAULT_SYSFS_ROOT, dev_root: Path = DEFAULT_DEV_ROOT
) -> UsbAccessProblem | None:
    """First Nikon USB device whose ``dev_root/BBB/DDD`` node is not readable and writable."""
    try:
        entries = sorted(Path(sysfs_root).iterdir())
    except OSError:
        return None
    for entry in entries:
        if _read(entry / "idVendor").lower() != NIKON_VENDOR_ID:
            continue
        try:
            bus = int(_read(entry / "busnum"))
            dev = int(_read(entry / "devnum"))
        except ValueError:
            continue
        node = Path(dev_root) / f"{bus:03d}" / f"{dev:03d}"
        if not os.access(node, os.R_OK | os.W_OK):
            return UsbAccessProblem(bus, dev, str(node), _read(entry / "product"))
    return None


USBDEVFS_RESET = 0x5514  # _IO('U', 20)


def reset_nikon_usb(
    sysfs_root: Path = DEFAULT_SYSFS_ROOT, dev_root: Path = DEFAULT_DEV_ROOT
) -> bool:
    """Best-effort libusb-style port reset (USBDEVFS_RESET) of every Nikon device node we can
    open. Returns True if at least one reset was issued. Never raises."""
    import fcntl

    done = False
    try:
        entries = sorted(Path(sysfs_root).iterdir())
    except OSError:
        return False
    for entry in entries:
        if _read(entry / "idVendor").lower() != NIKON_VENDOR_ID:
            continue
        try:
            node = (
                Path(dev_root)
                / f"{int(_read(entry / 'busnum')):03d}"
                / (f"{int(_read(entry / 'devnum')):03d}")
            )
            fd = os.open(node, os.O_WRONLY)
        except (ValueError, OSError):
            continue
        try:
            fcntl.ioctl(fd, USBDEVFS_RESET, 0)
            done = True
        except OSError:
            pass
        finally:
            os.close(fd)
    return done
