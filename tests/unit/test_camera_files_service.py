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


async def test_ledger_appends_one_line_per_file_and_keys_on_size_mtime(tmp_path: Path) -> None:
    p = tmp_path / "d" / "downloaded.jsonl"
    info = CameraFileInfo("/f", "a.jpg", 10, 5.5)
    led = DownloadLedger(p)
    await led.load()
    assert not led.has(info)
    await led.add(info)
    first = p.read_bytes()
    await led.add(CameraFileInfo("/f", "b.jpg", 1, 1.0))
    await led.add(info)  # duplicate: nothing written
    assert p.read_bytes().startswith(first)  # append-only, never rewritten
    assert len(p.read_text().splitlines()) == 2
    assert json.loads(p.read_text().splitlines()[0]) == ["/f", "a.jpg", 10, 5.5]
    led2 = DownloadLedger(p)
    await led2.load()
    assert led2.has(info)
    assert not led2.has(CameraFileInfo("/f", "a.jpg", 11, 5.5))  # size changed
    assert not led2.has(CameraFileInfo("/f", "a.jpg", 10, 6.0))  # mtime changed


async def test_ledger_tolerates_torn_last_line_and_repairs_it(tmp_path: Path) -> None:
    p = tmp_path / "downloaded.jsonl"
    p.write_bytes(b'["/f", "a.jpg", 10, 5.5]\n["/f", "b.jp')
    led = DownloadLedger(p)
    await led.load()
    assert led.has(CameraFileInfo("/f", "a.jpg", 10, 5.5))
    await led.add(CameraFileInfo("/f", "c.jpg", 3, 1.0))
    led2 = DownloadLedger(p)
    await led2.load()
    assert led2.has(CameraFileInfo("/f", "c.jpg", 3, 1.0))
    assert led2.has(CameraFileInfo("/f", "a.jpg", 10, 5.5))


async def test_ledger_migrates_legacy_json(tmp_path: Path) -> None:
    (tmp_path / "downloaded.json").write_text(
        json.dumps({"version": 1, "entries": [["/f", "a.jpg", 10, 5.5]]})
    )
    led = DownloadLedger(tmp_path / "downloaded.jsonl")
    await led.load()
    assert led.has(CameraFileInfo("/f", "a.jpg", 10, 5.5))
    assert (tmp_path / "downloaded.jsonl").exists()
    assert not (tmp_path / "downloaded.json").exists()
    led2 = DownloadLedger(tmp_path / "downloaded.jsonl")
    await led2.load()
    assert led2.has(CameraFileInfo("/f", "a.jpg", 10, 5.5))


async def test_ledger_corrupt_file_starts_empty(tmp_path: Path) -> None:
    p = tmp_path / "downloaded.jsonl"
    p.write_text("{not json")
    led = DownloadLedger(p)
    await led.load()
    assert not led.has(CameraFileInfo("/f", "a", 1, 1.0))
