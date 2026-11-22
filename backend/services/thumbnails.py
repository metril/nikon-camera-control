"""Cached JPEG thumbnails (Pillow, off the event loop). Never returns the original file."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from backend.core.errors import AppError, FileNotFoundError_
from backend.services.storage import classify

MIN_SIZE = 64
MAX_SIZE = 1024
DEFAULT_SIZE = 200  # fallback; normally config.media.thumbnail_size
_JPEG_QUALITY = 80
_SUBIFDS = 0x014A
_JPEG_OFFSET = 0x0201
_JPEG_LENGTH = 0x0202
_ORIENTATION = 0x0112


class UnsupportedMedia(AppError):
    code = "UNSUPPORTED_MEDIA"
    http_status = 415
    default_message = "No thumbnail can be generated for this file type"


def clamp_size(size: int) -> int:
    return max(MIN_SIZE, min(MAX_SIZE, size))


def _embedded_preview(path: Path, im: Image.Image) -> Image.Image | None:
    """Largest JPEG preview embedded in a TIFF-based RAW (SubIFDs / IFD1), else None."""
    best: Image.Image | None = None
    try:
        exif = im.getexif()
        ifds = [exif.get_ifd(_SUBIFDS)] if _SUBIFDS in exif else []
        ifds.append(exif.get_ifd(0x8769))
        offsets: list[tuple[int, int]] = []
        for ifd in ifds:
            if isinstance(ifd, dict) and _JPEG_OFFSET in ifd and _JPEG_LENGTH in ifd:
                offsets.append((int(ifd[_JPEG_OFFSET]), int(ifd[_JPEG_LENGTH])))
        sub = exif.get(_SUBIFDS)
        if isinstance(sub, tuple | list):
            for off in sub:
                d = exif.get_ifd(int(off)) if hasattr(exif, "get_ifd") else {}
                if _JPEG_OFFSET in d and _JPEG_LENGTH in d:
                    offsets.append((int(d[_JPEG_OFFSET]), int(d[_JPEG_LENGTH])))
        with path.open("rb") as fh:
            for off, length in offsets:
                if length <= 0:
                    continue
                fh.seek(off)
                data = fh.read(length)
                try:
                    cand = Image.open(io.BytesIO(data))
                    cand.load()
                except Exception:  # noqa: S112 - corrupt candidate, try the next
                    continue
                if best is None or cand.width * cand.height > best.width * best.height:
                    best = cand
    except Exception:
        return best
    return best


def _load_source(path: Path) -> Image.Image:
    kind = classify(path.name)
    if kind not in ("image", "raw"):
        raise UnsupportedMedia(f"No thumbnail for {path.suffix or 'this'} files")
    try:
        im = Image.open(path)
    except Exception as e:
        raise UnsupportedMedia("File is not a readable image") from e
    orientation = im.getexif().get(_ORIENTATION)
    if kind == "raw":
        preview = _embedded_preview(path, im)
        if preview is not None:
            if preview.getexif().get(_ORIENTATION) is None and orientation:
                preview.getexif()[_ORIENTATION] = orientation
            im.close()
            return preview
    try:
        im.load()
    except Exception as e:
        raise UnsupportedMedia("No embedded preview could be extracted") from e
    return im


def _render(src: Path, dest: Path, size: int) -> None:
    im = _load_source(src)
    try:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        rgb = im.convert("RGB")
        tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.tmp")
        try:
            rgb.save(tmp, "JPEG", quality=_JPEG_QUALITY, optimize=True)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        im.close()


class ThumbnailService:
    """``get(path, size)`` returns the cached JPEG thumbnail path, generating it if needed.

    ``path`` must already be a verified local file (use ``safe_join`` first).
    ``default_size`` is read live so config changes apply without a restart.
    """

    def __init__(self, data_dir: Path, default_size: Callable[[], int] = lambda: DEFAULT_SIZE):
        self._dir = data_dir / "thumbs"
        self._default = default_size
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(self, path: Path, size: int | None = None) -> Path:
        s = clamp_size(size if size is not None else self._default())
        try:
            st = await asyncio.to_thread(path.stat)
        except OSError as e:
            raise FileNotFoundError_() from e
        key = hashlib.sha1(
            f"{path}|{st.st_mtime_ns}|{st.st_size}|{s}".encode(), usedforsecurity=False
        ).hexdigest()
        dest = self._dir / f"{key}.jpg"
        if await asyncio.to_thread(dest.exists):
            return dest
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                if not await asyncio.to_thread(dest.exists):
                    await asyncio.to_thread(self._make, path, dest, s)
        finally:
            self._locks.pop(key, None)
        return dest

    def _make(self, src: Path, dest: Path, size: int) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        _render(src, dest, size)
