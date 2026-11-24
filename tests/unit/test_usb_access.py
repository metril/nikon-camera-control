from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gphoto2 as gp
import pytest

from backend.camera import gphoto2_backend
from backend.camera.gphoto2_backend import Gphoto2Backend
from backend.camera.usb_access import find_unopenable_nikon
from backend.core.errors import CameraNotFound, CameraPermissionDenied

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root can open any device node")


def _usb(tmp_path: Path, vendor: str, bus: int, dev: int, mode: int) -> tuple[Path, Path]:
    sysfs, devfs = tmp_path / "sys", tmp_path / "dev"
    entry = sysfs / f"{bus}-{dev}"
    entry.mkdir(parents=True)
    (entry / "idVendor").write_text(vendor + "\n")
    (entry / "busnum").write_text(f"{bus}\n")
    (entry / "devnum").write_text(f"{dev}\n")
    (entry / "product").write_text("D500\n")
    node = devfs / f"{bus:03d}" / f"{dev:03d}"
    node.parent.mkdir(parents=True)
    node.write_text("")
    node.chmod(mode)
    return sysfs, devfs


def test_unreadable_nikon_node_is_reported(tmp_path: Path) -> None:
    sysfs, devfs = _usb(tmp_path, "04b0", 1, 7, 0o000)
    problem = find_unopenable_nikon(sysfs, devfs)
    assert problem is not None
    assert (problem.bus, problem.device) == (1, 7)
    assert problem.path == str(devfs / "001" / "007")
    assert problem.details()["hints"]


def test_openable_nikon_and_other_vendors_are_fine(tmp_path: Path) -> None:
    sysfs, devfs = _usb(tmp_path, "04b0", 1, 7, 0o666)
    assert find_unopenable_nikon(sysfs, devfs) is None
    sysfs, devfs = _usb(tmp_path / "other", "1d6b", 2, 1, 0o000)
    assert find_unopenable_nikon(sysfs, devfs) is None
    assert find_unopenable_nikon(tmp_path / "missing", devfs) is None


class _FailingCamera:
    def init(self, ctx: Any) -> None:
        raise gp.GPhoto2Error(gp.GP_ERROR_MODEL_NOT_FOUND)

    def exit(self, ctx: Any) -> None:
        pass


def test_open_raises_permission_error_only_when_node_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gphoto2_backend.gp, "Camera", _FailingCamera)
    monkeypatch.setattr(gphoto2_backend.gp, "Context", lambda: object())
    sysfs, devfs = _usb(tmp_path, "04b0", 3, 9, 0o000)
    with pytest.raises(CameraPermissionDenied) as exc:
        Gphoto2Backend(sysfs, devfs).open()
    assert exc.value.http_status == 503
    assert exc.value.details["path"].endswith("003/009")

    (devfs / "003" / "009").chmod(0o666)
    with pytest.raises(CameraNotFound):
        Gphoto2Backend(sysfs, devfs).open()
