"""Shared local-storage helpers: safe path joins, collision-free names, camera downloads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
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


def _reader(f: CameraFilePath, part: Path) -> Callable[[CameraBackend], None]:
    def run(b: CameraBackend) -> None:
        b.read_file(f.folder, f.name, FileKind.NORMAL, part)

    return run


def _deleter(f: CameraFilePath) -> Callable[[CameraBackend], None]:
    def run(b: CameraBackend) -> None:
        b.delete_file(f.folder, f.name)

    return run


async def download_files(
    camera: CameraService,
    files: Sequence[CameraFilePath],
    dest_dir: Path,
    *,
    owner: str | None = None,
    delete_from_camera: bool = False,
    name_prefix: str = "",
) -> list[Path]:
    """Stream each camera file to ``dest_dir/<name_prefix><camera name>`` and return the
    local paths in order. Each file is written to ``.part`` then renamed atomically.
    A failed download removes its partial/placeholder files and re-raises; files already
    downloaded stay. Deleting from the camera happens only after a successful download and
    a failed delete is logged, not raised."""
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
        except BaseException:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
            raise
        out.append(final)
        if delete_from_camera:
            try:
                await camera.call(_deleter(f), owner=owner)
            except Exception:
                log.warning("could not delete %s/%s from camera", f.folder, f.name, exc_info=True)
    return out
