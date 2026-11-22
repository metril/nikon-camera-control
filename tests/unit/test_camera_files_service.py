import json
from pathlib import Path

import pytest

from backend.camera.backend import CameraFileInfo
from backend.core.errors import PathNotAllowed
from backend.services.camera_files import (
    DownloadLedger,
    file_type,
    join_camera_path,
    validate_camera_folder,
    validate_camera_name,
)


def test_validate_folder() -> None:
    assert validate_camera_folder("//a///b/") == "/a/b"
    assert validate_camera_folder("/") == "/"
    for bad in ("", "a/b", "/a/../b", "/a/./b", "/a\x00", "/a\\b"):
        with pytest.raises(PathNotAllowed):
            validate_camera_folder(bad)


def test_validate_name() -> None:
    assert validate_camera_name("DSC_1.NEF") == "DSC_1.NEF"
    for bad in ("", "..", ".", "a/b", "a\x00", "a\\b"):
        with pytest.raises(PathNotAllowed):
            validate_camera_name(bad)


def test_join_and_type() -> None:
    assert join_camera_path("/", "a") == "/a" and join_camera_path("/a", "b") == "/a/b"
    assert [file_type(n) for n in ("a.JPG", "a.nef", "a.MOV", "a.txt")] == [
        "jpeg",
        "raw",
        "video",
        "other",
    ]


async def test_ledger_persists_atomically_and_keys_on_size_mtime(tmp_path: Path) -> None:
    p = tmp_path / "d" / "downloaded.json"
    info = CameraFileInfo("/f", "a.jpg", 10, 5.5)
    led = DownloadLedger(p)
    await led.load()
    assert not led.has(info)
    await led.add(info)
    assert json.loads(p.read_text())["entries"] == [["/f", "a.jpg", 10, 5.5]]
    assert [f.name for f in p.parent.iterdir()] == ["downloaded.json"]  # no temp left
    led2 = DownloadLedger(p)
    await led2.load()
    assert led2.has(info)
    assert not led2.has(CameraFileInfo("/f", "a.jpg", 11, 5.5))  # size changed
    assert not led2.has(CameraFileInfo("/f", "a.jpg", 10, 6.0))  # mtime changed


async def test_ledger_corrupt_file_starts_empty(tmp_path: Path) -> None:
    p = tmp_path / "downloaded.json"
    p.write_text("{not json")
    led = DownloadLedger(p)
    await led.load()
    assert not led.has(CameraFileInfo("/f", "a", 1, 1.0))
