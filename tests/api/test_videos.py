"""Video rendering job + videos API. Uses the imageio-ffmpeg binary (dev dependency); the
tests are deliberately not marked ``ffmpeg`` (that marker skips on PATH lookups only)."""

from __future__ import annotations

import asyncio
import re
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
import imageio_ffmpeg
import pytest
from fastapi import FastAPI
from PIL import Image

from backend.api.schemas.sessions import BracketInfo, SessionFile, SessionFrame
from backend.api.v1.sessions import _make as make_sessions
from backend.core.events import EventBus
from backend.services.sessions import SessionStore
from backend.services.video import VideoService

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
S = "/api/v1/sessions"
V = "/api/v1/videos"


def _jpeg(path: Path, color: tuple[int, int, int] = (200, 30, 30), size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (size, size - 2), color).save(path, "JPEG")


def _nef(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (10, 120, 10)).save(path, "TIFF", compression="jpeg")


def _frame(i: int, files: list[SessionFile], **kw: object) -> SessionFrame:
    return SessionFrame(index=i, captured_at=datetime.now(UTC), files=files, set_index=i, **kw)  # type: ignore[arg-type]


async def _session(store: SessionStore, n: int = 10, *, raw: bool = False) -> str:
    m = await store.create("Night", {}, n)
    folder = store.folder(m.id)
    for i in range(n):
        name = f"2024-01-01T00-00-{i:02d}_DSC_{i}'x.{'nef' if raw else 'jpg'}"
        if raw:
            _nef(folder / "raw" / name)
        else:
            _jpeg(folder / "img" / name, (20 * i, 30, 30))
        kind: Literal["raw", "jpeg"] = "raw" if raw else "jpeg"
        sub = "raw" if raw else "img"
        await store.add_frame(m.id, _frame(i, [SessionFile(path=f"{sub}/{name}", kind=kind)]))
    return m.id


@pytest.fixture
async def ctx(app: FastAPI, client: httpx.AsyncClient) -> tuple[VideoService, SessionStore]:
    store = app.state.services.get("sessions", lambda: make_sessions(app.state))
    svc = app.state.services.get(
        "videos",
        lambda: VideoService(
            app.state.config_store,
            store,
            app.state.job_manager,
            app.state.data_dir,
            ffmpeg_path=FFMPEG,
            kill_grace_s=0.5,
        ),
    )
    return svc, store


def _install_fake(app: FastAPI, store: SessionStore, script: Path, **kw: float) -> None:
    app.state.services._services["videos"] = VideoService(  # replace the real one
        app.state.config_store,
        store,
        app.state.job_manager,
        app.state.data_dir,
        ffmpeg_path=str(script),
        kill_grace_s=0.5,
        **kw,
    )


def _fake_ffmpeg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "fakeffmpeg"
    p.write_text(f"#!{sys.executable}\nimport sys, time\nout = sys.argv[-1]\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


async def _wait_job(client: httpx.AsyncClient, job_id: str, limit: float = 60) -> dict:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        j = (await client.get(f"/api/v1/jobs/{job_id}")).json()
        if j["status"] in ("completed", "failed", "cancelled"):
            return j
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish")


def _frame_count(path: Path) -> int:
    r = subprocess.run(  # noqa: S603
        [FFMPEG, "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(re.findall(r"frame=\s*(\d+)", r.stderr)[-1])


async def _render(client: httpx.AsyncClient, sid: str, body: dict | None = None) -> dict:
    r = await client.post(f"{S}/{sid}/video", json=body or {})
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "render-video"
    return await _wait_job(client, r.json()["id"])


async def test_render_happy_path_manifest_and_progress(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    _, store = ctx
    sid = await _session(store, 10)
    bus: EventBus = app.state.event_bus
    events: list[dict] = []
    async with bus.subscribe() as sub:
        job = await _render(client, sid, {"fps": 10, "output_name": "my night.mp4"})
        while True:
            try:
                events.append((await asyncio.wait_for(sub.__anext__(), 0.05)).data)
            except TimeoutError:
                break
    assert job["status"] == "completed", job
    res = job["result"]
    assert res["name"] == "my_night.mp4" and res["frames"] == 10 and res["size"] > 0
    out = store.folder(sid) / "videos" / "my_night.mp4"
    assert out.is_file() and out.stat().st_size == res["size"]
    assert out.read_bytes()[4:8] == b"ftyp"
    assert _frame_count(out) == 10
    m = await store.get(sid)
    assert [(v.name, v.codec, v.fps) for v in m.videos] == [("my_night.mp4", "h264", 10)]
    assert not list(store.folder(sid).glob("videos/*.part*"))
    assert not list((app.state.data_dir / "video-tmp").glob("*"))
    assert any(e.get("job", {}).get("kind") == "render-video" for e in events)


async def test_progress_parsed_from_ffmpeg_progress_lines(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore], tmp_path: Path
) -> None:
    _, store = ctx
    sid = await _session(store, 10)
    script = _fake_ffmpeg(
        tmp_path,
        "print('frame=5', flush=True); print('progress=continue', flush=True)\n"
        "time.sleep(0.5)\nopen(out, 'wb').write(b'x' * 10)",
    )
    _install_fake(app, store, script)
    r = await client.post(f"{S}/{sid}/video", json={})
    jid = r.json()["id"]
    seen = 0.0
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and seen < 0.49:
        seen = (await client.get(f"/api/v1/jobs/{jid}")).json()["progress"]
        await asyncio.sleep(0.02)
    assert 0.49 <= seen < 1.0
    assert (await _wait_job(client, jid))["status"] == "completed"


@pytest.mark.parametrize(
    ("codec", "ext", "magic"),
    [("h265", ".mp4", b"ftyp"), ("prores", ".mov", b"ftyp"), ("vp9", ".webm", b"\x1a\x45\xdf\xa3")],
)
async def test_codecs_render(
    client: httpx.AsyncClient,
    ctx: tuple[VideoService, SessionStore],
    codec: str,
    ext: str,
    magic: bytes,
) -> None:
    _, store = ctx
    sid = await _session(store, 4)
    job = await _render(client, sid, {"codec": codec, "resolution": "720p", "deflicker": True})
    assert job["status"] == "completed", job
    out = store.folder(sid) / "videos" / job["result"]["name"]
    assert out.suffix == ext and out.read_bytes()[:12].find(magic) >= 0
    assert _frame_count(out) == 4


async def test_raw_only_frames_are_rendered_from_embedded_preview(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    """Regression: the legacy renderer fed NEF files to the concat demuxer."""
    _, store = ctx
    sid = await _session(store, 5, raw=True)
    job = await _render(client, sid)
    assert job["status"] == "completed", job
    assert _frame_count(store.folder(sid) / "videos" / job["result"]["name"]) == 5


async def test_frames_found_under_timestamped_names_in_subfolders(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    """Regression: legacy looked up camera names in the output root and found nothing;
    names here contain quotes/spaces (concat-list quoting broke on them)."""
    _, store = ctx
    sid = await _session(store, 3)
    job = await _render(client, sid)
    assert job["status"] == "completed" and job["result"]["frames"] == 3


async def test_bracket_selection(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    _, store = ctx
    m = await store.create("B", {}, 6)
    folder = store.folder(m.id)
    i = 0
    for s in range(2):
        for step in range(3):
            name = f"s{s}_{step}.jpg"
            _jpeg(folder / name, (80 * step, 0, 0))
            fr = SessionFrame(
                index=i,
                captured_at=datetime.now(UTC),
                files=[SessionFile(path=name, kind="jpeg")],
                bracket=BracketInfo(step_index=step),
                set_index=s,
            )
            await store.add_frame(m.id, fr)
            i += 1
    for choice, expected in (("middle", 2), ("first", 2), ("last", 2), (2, 2)):
        job = await _render(client, m.id, {"bracket_frame": choice})
        assert job["result"]["frames"] == expected, choice
    # middle really picks step 1 of each set
    got = await store.frame_files(m.id, middle_of_bracket=True)
    assert [p.name for p in got] == ["s0_1.jpg", "s1_1.jpg"]


async def test_zero_frames_is_invalid_state_not_ffmpeg_failure(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    _, store = ctx
    m = await store.create("Empty", {}, 0)
    r = await client.post(f"{S}/{m.id}/video", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    r = await client.post(f"{S}/20240101-000000-abcd/video", json={})
    assert r.status_code == 404


async def test_output_name_traversal_cannot_escape_or_overwrite(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    """Regression: output_filename was joined unsanitised and ffmpeg ran with -y."""
    _, store = ctx
    sid = await _session(store, 3)
    victim = app.state.output_dir / "victim.mp4"
    victim.write_bytes(b"precious")
    job = await _render(client, sid, {"output_name": "../../victim.mp4"})
    assert job["status"] == "completed" and job["result"]["name"] == "victim.mp4"
    assert victim.read_bytes() == b"precious"
    assert (store.folder(sid) / "videos" / "victim.mp4").is_file()
    for bad in ("x" * 200, "a/b\x00"):
        r = await client.post(f"{S}/{sid}/video", json={"output_name": bad})
        if len(bad) > 120:
            assert r.status_code == 422


async def test_second_render_never_overwrites(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    _, store = ctx
    sid = await _session(store, 3)
    a = await _render(client, sid, {"output_name": "same"})
    first = (store.folder(sid) / "videos" / "same.mp4").read_bytes()
    b = await _render(client, sid, {"output_name": "same"})
    assert (a["result"]["name"], b["result"]["name"]) == ("same.mp4", "same_1.mp4")
    assert (store.folder(sid) / "videos" / "same.mp4").read_bytes() == first
    assert len((await store.get(sid)).videos) == 2


async def test_cancel_terminates_ffmpeg_and_removes_partial_output(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore], tmp_path: Path
) -> None:
    _, store = ctx
    sid = await _session(store, 3)
    script = _fake_ffmpeg(
        tmp_path, "open(out, 'wb').write(b'partial')\nprint('frame=1', flush=True)\ntime.sleep(60)"
    )
    _install_fake(app, store, script)
    r = await client.post(f"{S}/{sid}/video", json={})
    jid = r.json()["id"]
    videos = store.folder(sid) / "videos"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not list(videos.glob("*.part.mp4")):  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    assert list(videos.glob("*.part.mp4"))
    # exclusive: a second render for the same session is refused while running
    r2 = await client.post(f"{S}/{sid}/video", json={})
    assert r2.status_code == 409
    await client.delete(f"/api/v1/jobs/{jid}")
    j = await _wait_job(client, jid)
    assert j["status"] == "cancelled"
    assert list(videos.iterdir()) == []
    assert (await store.get(sid)).videos == []


async def test_nonzero_exit_fails_with_bounded_stderr_tail(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore], tmp_path: Path
) -> None:
    _, store = ctx
    sid = await _session(store, 3)
    script = _fake_ffmpeg(
        tmp_path,
        "for i in range(500): print('noise line %d' % i * 5, file=sys.stderr)\n"
        "print('boom: encoder exploded', file=sys.stderr)\nsys.exit(3)",
    )
    _install_fake(app, store, script)
    j = await _render(client, sid)
    assert j["status"] == "failed" and j["error_code"] == "RENDER_FAILED"
    assert "boom: encoder exploded" in j["error"] and len(j["error"]) < 2300
    assert list((store.folder(sid) / "videos").iterdir()) == []


async def test_timeout_kills_ffmpeg(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore], tmp_path: Path
) -> None:
    _, store = ctx
    sid = await _session(store, 2)
    _install_fake(
        app,
        store,
        _fake_ffmpeg(tmp_path, "time.sleep(60)"),
        base_timeout_s=0.3,
        per_frame_timeout_s=0,
    )
    j = await _render(client, sid)
    assert j["status"] == "failed" and "timed out" in j["error"]


async def test_ffmpeg_missing_is_501(
    app: FastAPI, client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore], tmp_path: Path
) -> None:
    _, store = ctx
    sid = await _session(store, 2)
    svc = VideoService(
        app.state.config_store, store, app.state.job_manager, app.state.data_dir,
        ffmpeg_path=str(tmp_path / "nope"),
    )  # fmt: skip
    assert not svc.ffmpeg_available()
    app.state.services._services["videos"] = svc
    r = await client.post(f"{S}/{sid}/video", json={})
    assert r.status_code == 501 and r.json()["error"]["code"] == "FEATURE_UNSUPPORTED"


async def test_videos_list_download_range_delete(
    client: httpx.AsyncClient, ctx: tuple[VideoService, SessionStore]
) -> None:
    _, store = ctx
    sid = await _session(store, 5)
    other = await _session(store, 2)
    name = (await _render(client, sid, {"output_name": "a"}))["result"]["name"]
    await _render(client, other, {"output_name": "b"})
    body = (await client.get(V)).json()
    assert body["total"] == 2 and {i["name"] for i in body["items"]} == {"a.mp4", "b.mp4"}
    item = next(i for i in body["items"] if i["session_id"] == sid)
    assert item["path"] == f"sessions/{sid}/videos/a.mp4" and item["size"] > 0
    assert item["codec"] == "h264"
    assert (await client.get(V, params={"session_id": sid})).json()["total"] == 1

    full = await client.get(f"{V}/{sid}/{name}")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert full.headers["accept-ranges"] == "bytes"
    part = await client.get(f"{V}/{sid}/{name}", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == full.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(full.content)}"

    for bad in ("..%2f..%2fsession.json", "%2e%2e", "a%5cb"):
        r = await client.get(f"{V}/{sid}/{bad}")
        assert r.status_code in (400, 404), bad
        assert (await client.delete(f"{V}/{sid}/{bad}")).status_code in (400, 404)
    assert (await client.get(f"{V}/{sid}/session.json")).status_code == 404  # not in manifest

    assert (await client.delete(f"{V}/{sid}/{name}")).json() == {"ok": True}
    assert not (store.folder(sid) / "videos" / name).exists()
    assert (await store.get(sid)).videos == []
    assert (await client.get(f"{V}/{sid}/{name}")).status_code == 404
    assert (await client.delete(f"{V}/{sid}/{name}")).status_code == 404


async def test_routes_and_operation_ids(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    assert paths[f"{S}/{{session_id}}/video"]["post"]["operationId"] == "render_session_video"
    assert paths[V]["get"]["operationId"] == "list_videos"
    assert paths[f"{V}/{{session_id}}/{{name}}"]["get"]["operationId"] == "download_video"
    assert paths[f"{V}/{{session_id}}/{{name}}"]["delete"]["operationId"] == "delete_video"
