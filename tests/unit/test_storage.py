import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.core.errors import PathNotAllowed
from backend.services.storage import classify, download_files, safe_join, unique_path
from tests.conftest import TmpDirs


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
    assert (tmp_path / "20260101_120000_DSC_0001-1.NEF") in paths


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


async def test_app_startup_runs_cleanup(app: FastAPI, tmp_dirs: TmpDirs) -> None:
    leftover = tmp_dirs.output_dir / ".ncc" / "video-tmp" / "dead"
    leftover.mkdir(parents=True)
    (leftover / "000001.jpg").write_bytes(b"1")
    async with app.router.lifespan_context(app):
        assert not leftover.exists()


def test_sanitize_prefix_dashes() -> None:
    from backend.services.capture import sanitize_prefix

    assert sanitize_prefix("wedding day!") == "wedding-day-"
    assert sanitize_prefix("-a/b-") == "a-b-"
    assert sanitize_prefix("  ") == "" and sanitize_prefix(None) == ""


async def test_download_reserves_only_a_part_file_and_keeps_a_finished_file_on_cancel(
    app: FastAPI, connected_client: httpx.AsyncClient, tmp_path: Path
) -> None:
    svc = app.state.camera_service
    files = await svc.capture()
    out = tmp_path / "o"
    seen: list[list[str]] = []

    def stored(p: Path) -> None:
        seen.append(sorted(x.name for x in out.iterdir()))
        raise asyncio.CancelledError  # cancelled right after the rename

    with pytest.raises(asyncio.CancelledError):
        await download_files(svc, files[:1], out, on_stored=stored)
    (name,) = [x.name for x in out.iterdir()]
    assert not name.endswith(".part") and (out / name).stat().st_size > 0  # finished file kept
    assert seen == [[name]]


def test_reserve_part_leaves_no_empty_final_and_avoids_collisions(tmp_path: Path) -> None:
    from backend.services.storage import reserve_part

    f1, p1 = reserve_part(tmp_path, "a.jpg")
    f2, p2 = reserve_part(tmp_path, "a.jpg")
    assert not f1.exists() and p1.exists() and f2.name == "a-1.jpg" and p2.exists()
    f1.write_bytes(b"x")
    p1.unlink()
    assert reserve_part(tmp_path, "a.jpg")[0].name == "a-2.jpg"  # an existing final is not reused


def test_commit_part_never_replaces_a_file_that_appeared_after_reservation(tmp_path: Path) -> None:
    from backend.services.storage import commit_part, reserve_part

    final, part = reserve_part(tmp_path, "a.jpg")
    part.write_bytes(b"new")
    final.write_bytes(b"other writer")  # raced in between reserve and commit
    got = commit_part(part, final)
    assert final.read_bytes() == b"other writer"
    assert got.name == "a-1.jpg" and got.read_bytes() == b"new" and not part.exists()


def test_concurrent_commits_never_overwrite_without_hard_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """exFAT/FAT: os.link fails, so the exists-check + rename must be serialised per directory."""
    import errno
    import os
    import threading
    import time

    from backend.services import storage

    def no_link(*_a: object, **_k: object) -> None:
        raise OSError(errno.EPERM, "no hard links")

    real_replace = os.replace

    def slow_replace(src: object, dst: object) -> None:
        time.sleep(0.1)  # widen the check-then-rename window
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.os, "link", no_link)
    monkeypatch.setattr(storage.os, "replace", slow_replace)
    f1, p1 = storage.reserve_part(tmp_path, "a.jpg")
    f2, p2 = storage.reserve_part(tmp_path, "a.jpg")
    assert f2.name == "a-1.jpg"
    p1.write_bytes(b"one")
    p2.write_bytes(b"two")
    f1.write_bytes(b"other writer")  # appears after reservation: commit 1 moves on to a-1
    results: list[Path] = []
    threads = [
        threading.Thread(target=lambda a=a, b=b: results.append(storage.commit_part(a, b)))
        for a, b in ((p1, f1), (p2, f2))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 2
    assert sorted(x.read_bytes() for x in results) == [b"one", b"two"]
