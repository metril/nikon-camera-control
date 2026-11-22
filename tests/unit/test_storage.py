import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.core.errors import PathNotAllowed
from backend.services.storage import classify, download_files, safe_join, unique_path


@pytest.mark.parametrize(
    "rel", ["../x", "a/../../x", "/etc/passwd", "a\x00b", "..", "a/..", "C:/x", "a\\b"]
)
def test_safe_join_rejects(tmp_path: Path, rel: str) -> None:
    with pytest.raises(PathNotAllowed):
        safe_join(tmp_path, rel)


def test_safe_join_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    (root / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(PathNotAllowed):
        safe_join(root, "link/file.jpg")


def test_safe_join_ok(tmp_path: Path) -> None:
    assert safe_join(tmp_path, "") == tmp_path.resolve()
    assert safe_join(tmp_path, "a/b.jpg") == tmp_path.resolve() / "a" / "b.jpg"


def test_unique_path_does_not_collide_same_second(tmp_path: Path) -> None:
    paths = {unique_path(tmp_path, "20260101_120000_DSC_0001.NEF") for _ in range(5)}
    assert len(paths) == 5
    assert all(p.exists() for p in paths)
    assert (tmp_path / "20260101_120000_DSC_0001_1.NEF") in paths


async def test_unique_path_race_safe(tmp_path: Path) -> None:
    res = await asyncio.gather(
        *(asyncio.to_thread(unique_path, tmp_path, "a.jpg") for _ in range(20))
    )
    assert len(set(res)) == 20


def test_classify() -> None:
    assert classify("a.NEF") == "raw" and classify("a.JPG") == "image"
    assert classify("a.mov") == "video" and classify("a.txt") == "other"


async def test_download_files_atomic_and_ordered(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    svc = app.state.camera_service
    await svc.set_setting("imagequality", "NEF+JPEG Fine")
    files = await svc.capture()
    assert len(files) == 2
    out = await download_files(svc, files, tmp_path / "o", name_prefix="p_")
    assert [p.name for p in out] == [f"p_{f.name}" for f in files]
    assert all(p.stat().st_size > 0 for p in out)
    assert not list((tmp_path / "o").glob("*.part"))


def test_cleanup_stale_empties_tmp_dirs_and_removes_only_old_part_files(tmp_path: Path) -> None:
    import os
    import time

    from backend.services.storage import cleanup_stale

    data, out = tmp_path / "data", tmp_path / "out"
    for d in ("tmp/x", "video-tmp/y"):
        (data / d).mkdir(parents=True)
        (data / d / "f").write_bytes(b"1")
    (data / "tmp" / "loose").write_bytes(b"1")
    (out / "sessions" / "s" / "videos").mkdir(parents=True)
    old = out / "sessions" / "s" / "videos" / "a.part.mp4"
    new = out / "camera" / "b.NEF.part"
    new.parent.mkdir(parents=True)
    keep = out / "camera" / "c.NEF"
    old.write_bytes(b"1")
    new.write_bytes(b"1")
    keep.write_bytes(b"1")
    os.utime(old, (time.time() - 7200,) * 2)
    os.utime(keep, (time.time() - 7200,) * 2)
    cleanup_stale(data, out)
    assert list((data / "tmp").iterdir()) == [] and list((data / "video-tmp").iterdir()) == []
    assert not old.exists() and new.exists() and keep.exists()


async def test_app_startup_runs_cleanup(app: FastAPI) -> None:
    leftover = app.state.data_dir / "video-tmp" / "dead"
    leftover.mkdir(parents=True)
    (leftover / "000001.jpg").write_bytes(b"1")
    async with app.router.lifespan_context(app):
        assert not leftover.exists()
