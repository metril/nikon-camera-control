"""Pure helpers of the video service (argument builder, options, names, sequence prep)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from backend.api.schemas.videos import RenderRequest
from backend.services.video import (
    RenderOptions,
    build_ffmpeg_args,
    output_filename,
    parse_progress_line,
    prepare_sequence,
    resolve_options,
    target_size,
)


def _opts(**kw: object) -> RenderOptions:
    base: dict[str, object] = {
        "fps": 24, "codec": "h264", "crf": 20, "preset": "fast",
        "resolution": "source", "deflicker": False, "prores_profile": 2,
    }  # fmt: skip
    base.update(kw)
    return RenderOptions(**base)  # type: ignore[arg-type]


def _args(**kw: object) -> list[str]:
    return build_ffmpeg_args("ff", "/t/%06d.jpg", "/o/x.mp4", _opts(**kw), (1920, 1080))


def test_h264_args_use_configured_preset_and_crf_not_hardcoded_slow() -> None:
    a = _args()
    assert a[0] == "ff" and "-n" in a and "-y" not in a
    assert a[a.index("-crf") + 1] == "20" and a[a.index("-preset") + 1] == "fast"
    assert a[a.index("-c:v") + 1] == "libx264" and "slow" not in a
    assert a[a.index("-i") + 1] == "/t/%06d.jpg" and a[-1] == "/o/x.mp4"
    assert "concat" not in a


def test_h265_prores_vp9_args() -> None:
    h = _args(codec="h265")
    assert h[h.index("-c:v") + 1] == "libx265" and "hvc1" in h
    p = _args(codec="prores", prores_profile=3)
    assert p[p.index("-c:v") + 1] == "prores_ks" and p[p.index("-profile:v") + 1] == "3"
    assert "yuv422p10le" in p and "-crf" not in p
    v = _args(codec="vp9")
    assert v[v.index("-c:v") + 1] == "libvpx-vp9" and "-preset" not in v


def test_scale_and_deflicker_filters() -> None:
    a = _args(resolution="1080p", deflicker=True)
    vf = a[a.index("-vf") + 1]
    assert vf.startswith("deflicker") and "scale=1920:1080" in vf and "pad=1920:1080" in vf


def test_target_size_even_and_fitted() -> None:
    assert target_size((6001, 4001), "source") == (6000, 4000)
    assert target_size((6000, 4000), "1080p") == (1620, 1080)
    assert target_size((1, 1), "source") == (2, 2)


def test_resolve_options_defaults_and_overrides() -> None:
    cfg = {"cfg_codec": "libx265", "cfg_crf": 25, "cfg_preset": "slow", "cfg_fps": 30}
    o = resolve_options(RenderRequest(), **cfg)  # type: ignore[arg-type]
    assert (o.codec, o.crf, o.preset, o.fps) == ("h265", 25, "slow", 30)
    o = resolve_options(
        RenderRequest(codec="h264", quality="high", fps=12.5),
        **cfg,  # type: ignore[arg-type]
    )
    assert (o.codec, o.crf, o.fps, o.prores_profile) == ("h264", 18, 12.5, 3)
    o = resolve_options(RenderRequest(quality="high", crf=10), **cfg)  # type: ignore[arg-type]
    assert o.crf == 10


@pytest.mark.parametrize(
    ("requested", "codec", "expected"),
    [
        (None, "h264", "timelapse_x.mp4"),
        ("my video", "h264", "my_video.mp4"),
        ("clip.mov", "h264", "clip.mp4"),
        ("clip.mp4", "prores", "clip.mov"),
        ("a.b", "vp9", "a.b.webm"),
        ("../../etc/passwd", "h264", "passwd.mp4"),
        ("..\\..\\evil", "h265", "evil.mp4"),
        ("/abs/path/name.mp4", "h264", "name.mp4"),
        ("..", "h264", "timelapse_x.mp4"),
    ],
)
def test_output_filename_sanitised_and_extension_forced(
    requested: str | None, codec: str, expected: str
) -> None:
    assert output_filename(requested, "timelapse_x", codec) == expected


def test_parse_progress_line() -> None:
    assert parse_progress_line("frame=42") == 42
    assert parse_progress_line("fps=10") is None
    assert parse_progress_line("frame=N/A") is None


def test_prepare_sequence_numbers_links_and_converts(tmp_path: Path) -> None:
    jpg = tmp_path / "we ird'name.jpg"  # quotes/spaces never reach ffmpeg
    Image.new("RGB", (8, 8)).save(jpg)
    png = tmp_path / "b.png"
    Image.new("RGB", (8, 8)).save(png)
    bad = tmp_path / "c.nef"
    bad.write_bytes(b"junk")
    n = prepare_sequence([jpg, bad, png], tmp_path / "seq")
    assert n == 2
    names = sorted(p.name for p in (tmp_path / "seq").iterdir())
    assert names == ["000001.jpg", "000002.jpg"]
    with Image.open(tmp_path / "seq" / "000002.jpg") as im:
        assert im.format == "JPEG"
