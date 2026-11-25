import asyncio
import io
import random
import struct
from pathlib import Path

import pytest
from PIL import Image

from backend.camera.fake import _jpeg, _nef
from backend.core.errors import AppError, UnsupportedMedia
from backend.services.thumbnails import ThumbnailService, _tiff_jpeg_ranges, load_full_image


def _jpg(path: Path, size: tuple[int, int] = (800, 600), orientation: int | None = None) -> None:
    im = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    im.save(path, "JPEG", exif=exif)


async def test_jpeg_thumbnail_is_small_and_cached(tmp_path: Path) -> None:
    src = tmp_path / "a.jpg"
    _jpg(src)
    svc = ThumbnailService(tmp_path / "data", lambda: 128)
    t = await svc.get(src)
    assert t.parent == tmp_path / "data" / "thumbs"
    with Image.open(t) as im:
        assert max(im.size) == 128
    assert t.stat().st_size < src.stat().st_size
    assert await svc.get(src) == t
    assert (await svc.get(src, 5000)).name != t.name  # clamped to 1024, separate cache entry


async def test_exif_orientation_respected(tmp_path: Path) -> None:
    src = tmp_path / "r.jpg"
    _jpg(src, (800, 400), orientation=6)  # rotate 90 -> portrait
    t = await ThumbnailService(tmp_path / "d").get(src, 100)
    with Image.open(t) as im:
        assert im.height > im.width


async def test_nef_uses_embedded_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "a.NEF"
    src.write_bytes(_nef(_jpeg(["x"], random.Random(1))))  # noqa: S311
    t = await ThumbnailService(tmp_path / "d").get(src, 100)
    with Image.open(t) as im:
        assert im.format == "JPEG" and max(im.size) <= 100


async def test_unreadable_raw_is_415_not_original(tmp_path: Path) -> None:
    src = tmp_path / "bad.NEF"
    src.write_bytes(b"not an image" * 100)
    with pytest.raises(UnsupportedMedia) as ei:
        await ThumbnailService(tmp_path / "d").get(src)
    assert ei.value.http_status == 415 and isinstance(ei.value, AppError)


async def test_video_unsupported(tmp_path: Path) -> None:
    src = tmp_path / "a.mov"
    src.write_bytes(b"x")
    with pytest.raises(UnsupportedMedia):
        await ThumbnailService(tmp_path / "d").get(src)


def _jpeg_bytes(size: tuple[int, int], color: tuple[int, int, int] = (20, 160, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _synthetic_nef(big: bytes) -> bytes:
    """Little-endian TIFF: 8x6 grayscale IFD0 image (the "tiny thumbnail") and, like a Nikon
    NEF, a larger JPEG reachable only via SubIFD tag 0x014A -> 0x0201/0x0202."""
    pixels = bytes(range(48))
    n0 = 10  # IFD0 entries
    ifd0 = 8
    sub = ifd0 + 2 + n0 * 12 + 4
    pix = sub + 2 + 2 * 12 + 4
    jpg = pix + len(pixels)

    def ent(tag: int, typ: int, count: int, val: int) -> bytes:
        return struct.pack("<HHII", tag, typ, count, val)

    e0 = [
        ent(0x100, 4, 1, 8), ent(0x101, 4, 1, 6), ent(0x102, 3, 1, 8), ent(0x103, 3, 1, 1),
        ent(0x106, 3, 1, 1), ent(0x111, 4, 1, pix), ent(0x115, 3, 1, 1), ent(0x116, 4, 1, 6),
        ent(0x117, 4, 1, len(pixels)), ent(0x14A, 4, 1, sub),
    ]  # fmt: skip
    out = b"II*\x00" + struct.pack("<I", ifd0)
    out += struct.pack("<H", n0) + b"".join(e0) + struct.pack("<I", 0)
    out += struct.pack("<H", 2) + ent(0x201, 4, 1, jpg) + ent(0x202, 4, 1, len(big))
    out += struct.pack("<I", 0) + pixels
    assert len(out) == jpg
    return out + big


def test_subifd_jpeg_preferred_over_tiny_ifd0_image(tmp_path: Path) -> None:
    f = tmp_path / "x.NEF"
    f.write_bytes(_synthetic_nef(_jpeg_bytes((320, 240))))
    with Image.open(f) as plain:
        assert plain.size == (8, 6)  # what Pillow alone yields
    im = load_full_image(f)
    assert im.size == (320, 240) and im.format == "JPEG"


def test_tiff_parser_finds_subifd_jpeg_range(tmp_path: Path) -> None:
    big = _jpeg_bytes((100, 80))
    data = _synthetic_nef(big)
    assert _tiff_jpeg_ranges(data) == [(len(data) - len(big), len(big))]


def test_byte_scan_finds_jpeg_not_referenced_by_any_tag(tmp_path: Path) -> None:
    data = _synthetic_nef(_jpeg_bytes((300, 200)))
    # corrupt the SubIFD pointer so only the scan can locate the JPEG
    data = data.replace(
        struct.pack("<HHII", 0x14A, 4, 1, 8 + 2 + 120 + 4), struct.pack("<HHII", 0x14A, 4, 1, 0)
    )
    f = tmp_path / "y.NEF"
    f.write_bytes(data)
    assert _tiff_jpeg_ranges(data) == []
    assert load_full_image(f).size == (300, 200)


def test_largest_candidate_wins_and_garbage_is_ignored(tmp_path: Path) -> None:
    data = (
        _synthetic_nef(_jpeg_bytes((120, 90))) + b"\xff\xd8\xff\xe0garbage" + _jpeg_bytes((50, 40))
    )
    f = tmp_path / "z.NEF"
    f.write_bytes(data)
    assert load_full_image(f).size == (120, 90)


def test_truncated_tiff_offsets_do_not_crash(tmp_path: Path) -> None:
    data = _synthetic_nef(_jpeg_bytes((100, 80)))[:150]
    assert _tiff_jpeg_ranges(data) == []  # bounds-checked, no struct.error escapes


async def test_renders_are_capped_and_cache_is_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from backend.services import thumbnails as th

    srcs = []
    for i in range(6):
        p = tmp_path / f"{i}.jpg"
        _jpg(p, (300 + i, 200))
        srcs.append(p)
    svc = ThumbnailService(tmp_path / "d", lambda: 100)
    live = peak = 0
    lock = threading.Lock()
    real = th._render

    def counting(src: Path, dest: Path, size: int) -> None:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        try:
            import time

            time.sleep(0.05)
            real(src, dest, size)
        finally:
            with lock:
                live -= 1

    monkeypatch.setattr(th, "_render", counting)
    await asyncio.gather(*(svc.get(p) for p in srcs))
    assert 1 <= peak <= th.MAX_CONCURRENT_RENDERS
    th._prune(tmp_path / "d" / "thumbs", 2)
    assert len(list((tmp_path / "d" / "thumbs").glob("*.jpg"))) == 2


def test_jpeg_thumbnail_uses_draft_mode_and_keeps_size(tmp_path: Path) -> None:
    src = tmp_path / "big.jpg"
    _jpg(src, (4000, 3000))
    dest = tmp_path / "t.jpg"
    from backend.services.thumbnails import _render

    _render(src, dest, 200)
    with Image.open(dest) as im:
        assert max(im.size) == 200


def test_draft_is_requested_before_the_jpeg_is_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import JpegImagePlugin

    f = tmp_path / "big.jpg"
    f.write_bytes(_jpeg_bytes((2000, 1500)))
    order: list[str] = []
    real_draft, real_load = JpegImagePlugin.JpegImageFile.draft, JpegImagePlugin.JpegImageFile.load

    def draft(self, *a):  # type: ignore[no-untyped-def]
        order.append("draft")
        return real_draft(self, *a)

    def load(self):  # type: ignore[no-untyped-def]
        order.append("load")
        return real_load(self)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", draft)
    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "load", load)
    im = load_full_image(f, draft_size=100)
    assert order[:2] == ["draft", "load"]
    assert im.size[0] < 2000  # decoded at reduced scale
