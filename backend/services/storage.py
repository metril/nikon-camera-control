"""Shared local-storage helpers: safe path joins, collision-free names, camera downloads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from backend.camera.backend import CameraBackend, CameraFilePath, FileKind
from backend.core.camera_service import CameraService
from backend.core.errors import PathNotAllowed

log = logging.getLogger(__name__)

MediaKindName = Literal["image", "raw", "video", "other"]

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
RAW_EXTS = frozenset({".nef", ".nrw", ".cr2", ".cr3", ".arw", ".dng", ".raf", ".orf", ".rw2"})
VIDEO_EXTS = frozenset({".mov", ".mp4", ".avi", ".mkv", ".m4v"})

DOWNLOAD_TIMEOUT_S = 120.0
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def classify(name: str) -> MediaKindName:
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in RAW_EXTS:
        return "raw"
    if ext in VIDEO_EXTS:
        return "video"
    return "other"


def sanitize_name(name: str, *, default: str = "file") -> str:
    """Reduce ``name`` to a safe single path component (letters, digits, ``._-``)."""
    cleaned = _UNSAFE.sub("_", os.path.basename(name.replace("\\", "/"))).strip("._")
    return cleaned or default


def safe_join(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``; raise PathNotAllowed if it escapes.

    Rejects absolute paths, ``..`` segments, NUL bytes and symlinks pointing outside.
    An empty string yields the root itself.
    """
    if "\x00" in relative or "\\" in relative:
        raise PathNotAllowed("Invalid path")
    if relative.startswith("/") or re.match(r"^[A-Za-z]:", relative):
        raise PathNotAllowed("Absolute paths are not allowed")
    if any(part == ".." for part in relative.split("/")):
        raise PathNotAllowed("Path traversal is not allowed")
    base = root.resolve()
    try:
        full = (base / relative).resolve()
    except (OSError, ValueError, RuntimeError) as e:
        raise PathNotAllowed("Invalid path") from e
    if full != base and not full.is_relative_to(base):
        raise PathNotAllowed()
    return full


def unique_path(dest_dir: Path, name: str) -> Path:
    """Create (O_EXCL) and return a fresh empty file ``dest_dir/name``; on collision
    append ``_1``, ``_2``... before the extension. Race-safe across threads/processes."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = sanitize_name(name)
    stem, ext = os.path.splitext(name)
    n = 0
    while True:
        candidate = dest_dir / (name if n == 0 else f"{stem}_{n}{ext}")
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            n += 1
            continue
        return candidate


def _notify_stored(on_stored: Callable[[Path], None], path: Path) -> None:
    try:
        on_stored(path)
    except Exception:  # hashing/bookkeeping must never lose a capture
        log.exception("post-store hook failed for %s", path)


def _reader(f: CameraFilePath, part: Path) -> Callable[[CameraBackend], None]:
    def run(b: CameraBackend) -> None:
        b.read_file(f.folder, f.name, FileKind.NORMAL, part)

    return run


def _deleter(f: CameraFilePath) -> Callable[[CameraBackend], None]:
    def run(b: CameraBackend) -> None:
        b.delete_file(f.folder, f.name)

    return run


async def _verified(
    camera: CameraService, f: CameraFilePath, local: Path, owner: str | None
) -> bool:
    """True if ``local`` matches the camera's size for ``f`` (non-empty when the camera does not
    report one). Any error counts as not verified."""

    def size(b: CameraBackend) -> int:
        return next((i.size for i in b.list_files(f.folder) if i.name == f.name), 0)

    try:
        want = await camera.call(size, owner=owner)
        have = (await asyncio.to_thread(local.stat)).st_size
    except Exception:
        return False
    return have == want if want > 0 else have > 0


async def download_files(
    camera: CameraService,
    files: Sequence[CameraFilePath],
    dest_dir: Path,
    *,
    owner: str | None = None,
    delete_from_camera: bool = False,
    name_prefix: str = "",
    on_stored: Callable[[Path], None] | None = None,
) -> list[Path]:
    """Stream each camera file to ``dest_dir/<name_prefix><camera name>`` and return the
    local paths in order. Each file is written to ``.part`` then renamed atomically.
    A failed download removes its partial/placeholder files and re-raises; files already
    downloaded stay. Deleting from the camera happens only after a successful download and
    the local copy is first checked against the camera's file size (unverified files stay on the
    camera), and a failed delete is logged, not raised."""
    out: list[Path] = []
    for f in files:
        final = await asyncio.to_thread(unique_path, dest_dir, f"{name_prefix}{f.name}")
        part = final.with_name(final.name + ".part")
        try:
            await camera.call(
                _reader(f, part),
                timeout=DOWNLOAD_TIMEOUT_S,
                owner=owner,
            )
            await asyncio.to_thread(os.replace, part, final)
            if on_stored is not None:
                await asyncio.to_thread(_notify_stored, on_stored, final)
        except BaseException:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
            raise
        out.append(final)
        if delete_from_camera:
            if not await _verified(camera, f, final, owner):
                log.warning(
                    "not deleting %s/%s from camera: download not verified", f.folder, f.name
                )
                continue
            try:
                await camera.call(_deleter(f), owner=owner)
            except Exception:
                log.warning("could not delete %s/%s from camera", f.folder, f.name, exc_info=True)
    return out


STALE_PART_AGE_S = 3600.0
_PART_SCAN_DEPTH = 4  # output/sessions/<id>/videos/x.part


def _sweep_parts(root: Path, cutoff: float, depth: int) -> None:
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                if depth > 0:
                    _sweep_parts(Path(e.path), cutoff, depth - 1)
            elif e.name.endswith(".part") or ".part." in e.name:
                if e.stat(follow_symlinks=False).st_mtime < cutoff:
                    os.unlink(e.path)
        except OSError:
            continue


def cleanup_stale(
    cache_dir: Path, output_dir: Path, *, part_max_age_s: float = STALE_PART_AGE_S
) -> None:
    """Housekeeping when a target becomes available (blocking; run in a thread): empty
    ``<cache>/tmp`` and ``<cache>/video-tmp`` (nothing survives a restart) and delete ``*.part``
    files under the output dir older than ``part_max_age_s`` (interrupted downloads/renders)."""
    for name in ("tmp", "video-tmp"):
        d = cache_dir / name
        if d.is_dir():
            for child in d.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    with contextlib.suppress(OSError):
                        child.unlink()
    _sweep_parts(output_dir, time.time() - part_max_age_s, _PART_SCAN_DEPTH)
