"""Cached JPEG thumbnails (Pillow, off the event loop). Never returns the original file."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import logging
import mmap
import os
import struct
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from backend.core.errors import FileNotFoundError_, UnsupportedMedia
from backend.services.storage import classify

log = logging.getLogger(__name__)

MIN_SIZE = 64
MAX_SIZE = 1024
DEFAULT_SIZE = 200  # fallback; normally config.media.thumbnail_size
_JPEG_QUALITY = 80
_SUBIFDS = 0x014A
_JPEG_OFFSET = 0x0201
_JPEG_LENGTH = 0x0202
_ORIENTATION = 0x0112
MAX_CONCURRENT_RENDERS = 2  # full decodes are memory-heavy; the rest wait
CACHE_MAX_ENTRIES = 5000
CACHE_PRUNE_EVERY = 200  # renders between prune passes


def _prune(cache: Path, keep: int) -> None:
    """Delete the oldest cached thumbnails beyond ``keep`` (blocking)."""
    try:
        files = sorted(
            (e for e in os.scandir(cache) if e.name.endswith(".jpg")),
            key=lambda e: e.stat().st_mtime,
        )
    except OSError:
        return
    for e in files[: max(0, len(files) - keep)]:
        with contextlib.suppress(OSError):
            os.unlink(e.path)


def clamp_size(size: int) -> int:
    return max(MIN_SIZE, min(MAX_SIZE, size))


_MAX_PREVIEW_BYTES = 64 * 1024 * 1024
_MAX_SCAN_HITS = 64  # SOI markers examined by the byte scan
_MAX_IFDS = 16
_SOI = b"\xff\xd8\xff"
_TYPE_SIZE = {3: 2, 4: 4}  # SHORT, LONG: the only types of the tags we read


class _Window(io.RawIOBase):
    """Read-only view of ``buf[start:]`` (an mmap or bytes) usable as a file by Pillow."""

    def __init__(self, buf: mmap.mmap | bytes, start: int, end: int) -> None:
        self._buf, self._start, self._end, self._pos = buf, start, end, start

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos - self._start

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        base = {os.SEEK_SET: self._start, os.SEEK_CUR: self._pos, os.SEEK_END: self._end}[whence]
        self._pos = max(self._start, min(self._end, base + offset))
        return self._pos - self._start

    def readinto(self, b: Any) -> int:
        n = min(len(b), self._end - self._pos)
        b[:n] = self._buf[self._pos : self._pos + n]
        self._pos += n
        return n


def _tiff_jpeg_ranges(buf: mmap.mmap | bytes) -> list[tuple[int, int]]:
    """(offset, length) of JPEGs referenced by TIFF tags 0x0201/0x0202 in IFD0, IFD1 and
    any SubIFD listed in tag 0x014A (parsed by hand: Pillow does not expose them for NEFs)."""
    size = len(buf)
    if size < 8 or bytes(buf[:2]) not in (b"II", b"MM"):
        return []
    end = "<" if bytes(buf[:2]) == b"II" else ">"
    if struct.unpack_from(end + "H", buf, 2)[0] != 42:
        return []
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    todo = [struct.unpack_from(end + "I", buf, 4)[0]]
    while todo and len(seen) < _MAX_IFDS:
        off = todo.pop(0)
        if off in seen or off < 8 or off + 2 > size:
            continue
        seen.add(off)
        n = struct.unpack_from(end + "H", buf, off)[0]
        if off + 2 + n * 12 + 4 > size:
            continue
        tags: dict[int, list[int]] = {}
        for i in range(n):
            tag, typ, count, val = struct.unpack_from(end + "HHI4s", buf, off + 2 + i * 12)
            width = _TYPE_SIZE.get(typ)
            if tag not in (_SUBIFDS, _JPEG_OFFSET, _JPEG_LENGTH) or width is None:
                continue
            count = min(count, 32)
            code = "H" if typ == 3 else "I"
            if width * count <= 4:
                where = off + 2 + i * 12 + 8
            else:
                where = struct.unpack(end + "I", val)[0]
                if where + width * count > size:
                    continue
            tags[tag] = list(struct.unpack_from(f"{end}{count}{code}", buf, where))
        if _JPEG_OFFSET in tags and _JPEG_LENGTH in tags:
            o, ln = tags[_JPEG_OFFSET][0], tags[_JPEG_LENGTH][0]
            if 0 < ln <= _MAX_PREVIEW_BYTES and o + ln <= size:
                out.append((o, ln))
        todo += tags.get(_SUBIFDS, [])
        todo.append(struct.unpack_from(end + "I", buf, off + 2 + n * 12)[0])  # next IFD
    return out


def _scan_jpeg_starts(buf: mmap.mmap | bytes) -> list[int]:
    out: list[int] = []
    pos = buf.find(_SOI)
    while pos != -1 and len(out) < _MAX_SCAN_HITS:
        out.append(pos)
        pos = buf.find(_SOI, pos + 1)
    return out


def _embedded_preview(
    path: Path, im: Image.Image, draft_size: int | None = None
) -> Image.Image | None:
    """Largest image among: JPEGs referenced by TIFF/SubIFD tags, JPEG streams found by a
    bounded byte scan, and Pillow's own decode (``im``). Memory-safe: the file is mmapped and
    only the winning candidate is decoded. Returns None if nothing beats failing outright."""
    try:
        with path.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            spans: dict[int, int] = {}
            with contextlib.suppress(Exception):  # malformed TIFF: fall through to the scan
                for off, ln in _tiff_jpeg_ranges(buf):
                    spans[off] = off + ln
            for off in _scan_jpeg_starts(buf):
                spans.setdefault(off, min(len(buf), off + _MAX_PREVIEW_BYTES))
            cands: list[tuple[int, Image.Image]] = []
            for off, stop in spans.items():
                try:
                    opened = Image.open(io.BufferedReader(_Window(buf, off, stop)))
                    cands.append((opened.width * opened.height, opened))
                except Exception:  # noqa: S112 - not a decodable JPEG, ignore
                    continue
            cands.append((im.width * im.height, im))
            cands.sort(key=lambda c: c[0], reverse=True)
            for _, choice in cands:
                try:
                    _draft(choice, draft_size)
                    choice.load()
                except Exception:  # noqa: S112 - e.g. raw sensor data Pillow cannot decode
                    continue
                if choice is im:
                    return None  # Pillow's own decode is the best available
                return choice
    except Exception:
        log.warning("embedded preview extraction failed for %s", path, exc_info=True)
    return None


def _draft(im: Image.Image, draft_size: int | None) -> None:
    """Ask the JPEG decoder for a reduced-scale decode (never below 2x ``draft_size``).
    Must run before ``load()``: afterwards it is a no-op."""
    if draft_size and im.format == "JPEG" and im.mode in ("RGB", "L"):
        im.draft("RGB", (draft_size * 2, draft_size * 2))


def load_full_image(path: Path, draft_size: int | None = None) -> Image.Image:
    kind = classify(path.name)
    if kind not in ("image", "raw"):
        raise UnsupportedMedia(f"No thumbnail for {path.suffix or 'this'} files")
    try:
        im = Image.open(path)
    except Exception as e:
        raise UnsupportedMedia("File is not a readable image") from e
    orientation = im.getexif().get(_ORIENTATION)
    if kind == "raw":
        preview = _embedded_preview(path, im, draft_size)
        if preview is not None:
            if preview.getexif().get(_ORIENTATION) is None and orientation:
                preview.getexif()[_ORIENTATION] = orientation
            im.close()
            return preview
    try:
        _draft(im, draft_size)
        im.load()
    except Exception as e:
        raise UnsupportedMedia("No embedded preview could be extracted") from e
    return im


def _render(src: Path, dest: Path, size: int, quality: int = _JPEG_QUALITY) -> None:
    im = load_full_image(src, draft_size=size)
    try:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        rgb = im.convert("RGB")
        tmp = dest.with_name(f"{dest.name}.{uuid.uuid4().hex}.tmp")
        try:
            rgb.save(tmp, "JPEG", quality=quality, optimize=True)
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

    def __init__(
        self,
        cache_dir: Path | Callable[[], Path],
        default_size: Callable[[], int] = lambda: DEFAULT_SIZE,
    ):
        self._cache = cache_dir if callable(cache_dir) else (lambda: cache_dir)
        self._default = default_size
        self._locks: dict[str, asyncio.Lock] = {}
        self._renders = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)
        self._rendered = 0

    @property
    def _dir(self) -> Path:
        return self._cache() / "thumbs"

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
                    async with self._renders:
                        await asyncio.to_thread(self._make, path, dest, s)
                    self._rendered += 1
                    if self._rendered % CACHE_PRUNE_EVERY == 0:
                        await asyncio.to_thread(_prune, self._dir, CACHE_MAX_ENTRIES)
        finally:
            self._locks.pop(key, None)
        return dest

    def _make(self, src: Path, dest: Path, size: int) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        _render(src, dest, size)


def render_preview(src: Path, dest: Path, size: int, quality: int) -> None:
    """Screen-sized JPEG of an image or RAW (embedded preview), long edge <= ``size`` (blocking)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _render(src, dest, size, quality)
