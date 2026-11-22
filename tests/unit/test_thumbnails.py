import random
from pathlib import Path

import pytest
from PIL import Image

from backend.camera.fake import _jpeg, _nef
from backend.core.errors import AppError, UnsupportedMedia
from backend.services.thumbnails import ThumbnailService


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
