"""Render time-lapse session frames into a video with ffmpeg (as a cancellable job).

Frames come from ``SessionStore.frame_files`` (or, for first/last/step bracket choices,
the same resolution rules applied to a different step). Non-JPEG frames (RAW, TIFF, PNG)
are converted to a full-size JPEG in a temp folder under the data dir. The frames are
linked/copied as ``000001.jpg ...`` and read through ffmpeg's image2 pattern, so file names
never reach ffmpeg's parser. ffmpeg is always run as an argv list; its output goes to a
``.part`` file that replaces the reserved (never overwritten) final name on success.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import ImageOps

from backend.api.schemas.sessions import SessionFrame, SessionVideo
from backend.api.schemas.videos import RenderRequest
from backend.core.config_store import ConfigStore
from backend.core.errors import (
    AppError,
    FeatureUnsupported,
    FileNotFoundError_,
    InvalidState,
    PathNotAllowed,
    SessionNotFound,
)
from backend.core.jobs import Job, JobContext, JobManager
from backend.services.sessions import SessionStore
from backend.services.storage import VIDEO_EXTS, safe_join, sanitize_name, unique_path
from backend.services.thumbnails import _load_source

log = logging.getLogger(__name__)

BASE_TIMEOUT_S = 120.0
PER_FRAME_TIMEOUT_S = 2.0  # wall-clock budget per frame (RAW preview extraction + encode)
KILL_GRACE_S = 5.0
STDERR_TAIL_CHARS = 2000
JPEG_EXTS = frozenset({".jpg", ".jpeg"})
_LEGACY_CRF = {
    "h264": {"low": 28, "medium": 23, "high": 18},
    "h265": {"low": 30, "medium": 25, "high": 20},
    "vp9": {"low": 36, "medium": 31, "high": 26},
}
_PRORES_PROFILE = {"low": 1, "medium": 2, "high": 3}  # LT, Standard, HQ
_CONFIG_CODEC = {"libx264": "h264", "libx265": "h265", "libvpx-vp9": "vp9"}
_EXT = {"h264": ".mp4", "h265": ".mp4", "prores": ".mov", "vp9": ".webm"}
_BOX = {"2160p": (3840, 2160), "1080p": (1920, 1080), "720p": (1280, 720)}


class _Empty:
    def __aiter__(self) -> _Empty:
        return self

    async def __anext__(self) -> bytes:
        raise StopAsyncIteration


_EMPTY = _Empty()


class RenderFailed(AppError):
    code = "RENDER_FAILED"
    http_status = 500
    default_message = "Video rendering failed"


@dataclass(frozen=True)
class RenderOptions:
    """Fully resolved options (request merged with config defaults)."""

    fps: float
    codec: str
    crf: int
    preset: str
    resolution: str
    deflicker: bool
    prores_profile: int


def resolve_options(
    req: RenderRequest, *, cfg_codec: str, cfg_crf: int, cfg_preset: str, cfg_fps: float
) -> RenderOptions:
    codec = req.codec or _CONFIG_CODEC.get(cfg_codec, "h264")
    quality = req.quality
    if req.crf is not None:
        crf = req.crf
    elif quality is not None and codec in _LEGACY_CRF:
        crf = _LEGACY_CRF[codec][quality]
    else:
        crf = cfg_crf
    return RenderOptions(
        fps=req.fps or cfg_fps,
        codec=codec,
        crf=crf,
        preset=req.preset or cfg_preset,
        resolution=req.resolution,
        deflicker=req.deflicker,
        prores_profile=_PRORES_PROFILE[quality or "medium"],
    )


def build_ffmpeg_args(ffmpeg: str, pattern: str, output: str, opts: RenderOptions) -> list[str]:
    """Pure argv builder (no shell). ``output`` must not exist (``-n``)."""
    if opts.resolution in _BOX:
        w, h = _BOX[opts.resolution]
        scale = f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    else:
        scale = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    filters = (["deflicker=mode=pm:size=10"] if opts.deflicker else []) + [scale]
    argv = [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats",
        "-progress", "pipe:1", "-n",
        "-framerate", f"{opts.fps:g}", "-i", pattern,
        "-vf", ",".join(filters),
    ]  # fmt: skip
    if opts.codec == "h264":
        argv += ["-c:v", "libx264", "-crf", str(opts.crf), "-preset", opts.preset]
        argv += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    elif opts.codec == "h265":
        argv += ["-c:v", "libx265", "-crf", str(opts.crf), "-preset", opts.preset]
        argv += ["-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-movflags", "+faststart"]
    elif opts.codec == "prores":
        argv += ["-c:v", "prores_ks", "-profile:v", str(opts.prores_profile)]
        argv += ["-pix_fmt", "yuv422p10le"]
    elif opts.codec == "vp9":
        argv += ["-c:v", "libvpx-vp9", "-crf", str(opts.crf), "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:  # pragma: no cover - guarded by the request schema
        raise ValueError(f"unknown codec {opts.codec}")
    argv += ["-an", "-r", f"{opts.fps:g}", output]
    return argv


def output_filename(requested: str | None, default: str, codec: str) -> str:
    """Sanitised file name with the extension forced by the codec."""
    stem, ext = os.path.splitext(sanitize_name(requested or default, default=default))
    if ext.lower() not in VIDEO_EXTS | {".webm"}:
        stem = stem + ext
    return f"{sanitize_name(stem, default=default)}{_EXT[codec]}"


def find_ffmpeg(configured: str | None = None) -> str | None:
    if configured:
        return configured if shutil.which(configured) or Path(configured).is_file() else None
    return shutil.which("ffmpeg")


def parse_progress_line(line: str) -> int | None:
    """Frame number from an ffmpeg ``-progress`` ``frame=N`` line, else None."""
    if line.startswith("frame="):
        try:
            return int(line[6:].strip())
        except ValueError:
            return None
    return None


def _to_jpeg(src: Path, dest: Path) -> None:
    im = _load_source(src)
    try:
        ImageOps.exif_transpose(im).convert("RGB").save(dest, "JPEG", quality=92)
    finally:
        im.close()


def prepare_sequence(frames: list[Path], seq_dir: Path) -> int:
    """Link (or copy) / convert ``frames`` to ``seq_dir/000001.jpg ...``. Returns the count
    of frames written; unreadable frames are skipped (numbering stays gapless)."""
    seq_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for src in frames:
        dest = seq_dir / f"{n + 1:06d}.jpg"
        try:
            if src.suffix.lower() in JPEG_EXTS:
                try:
                    os.symlink(src, dest)
                except OSError:
                    shutil.copyfile(src, dest)
            else:
                _to_jpeg(src, dest)
        except Exception:
            log.warning("skipping unreadable frame %s", src, exc_info=True)
            dest.unlink(missing_ok=True)
            continue
        n += 1
    return n


class VideoService:
    def __init__(
        self,
        config: ConfigStore,
        sessions: SessionStore,
        jobs: JobManager,
        data_dir: Path,
        *,
        ffmpeg_path: str | None = None,
        base_timeout_s: float = BASE_TIMEOUT_S,
        per_frame_timeout_s: float = PER_FRAME_TIMEOUT_S,
        kill_grace_s: float = KILL_GRACE_S,
    ) -> None:
        self._config = config
        self._sessions = sessions
        self._jobs = jobs
        self._tmp_root = Path(data_dir) / "video-tmp"
        self._ffmpeg_path = ffmpeg_path
        self._base_timeout = base_timeout_s
        self._per_frame = per_frame_timeout_s
        self._grace = kill_grace_s

    # ---- ffmpeg ----------------------------------------------------------------------
    def _configured_path(self) -> str | None:
        if self._ffmpeg_path:
            return self._ffmpeg_path
        return getattr(self._config.config.video, "ffmpeg_path", None) or None

    def ffmpeg_available(self) -> bool:
        return find_ffmpeg(self._configured_path()) is not None

    def _require_ffmpeg(self) -> str:
        path = find_ffmpeg(self._configured_path())
        if path is None:
            raise FeatureUnsupported(
                "ffmpeg was not found. Install ffmpeg (e.g. 'apt install ffmpeg') or set the "
                "ffmpeg path in the video settings.",
            )
        return path

    # ---- frame selection -------------------------------------------------------------
    async def _select_frames(self, session_id: str, choice: str | int) -> list[Path]:
        if choice == "middle":
            return await self._sessions.frame_files(
                session_id, prefer="jpeg", middle_of_bracket=True
            )
        frames = await self._sessions.list_frames(session_id, 0, None)
        folder = self._sessions.folder(session_id).resolve()
        groups: dict[Any, list[SessionFrame]] = {}
        for fr in frames:
            key = ("set", fr.set_index) if fr.bracket else ("f", fr.index)
            groups.setdefault(key, []).append(fr)

        def pick() -> list[Path]:
            out: list[Path] = []
            for g in groups.values():
                g.sort(key=lambda f: (f.bracket.step_index if f.bracket else 0, f.index))
                if choice == "first":
                    i = 0
                elif choice == "last":
                    i = len(g) - 1
                else:
                    i = min(int(choice), len(g) - 1)
                for f in sorted(g[i].files, key=lambda x: 0 if x.kind == "jpeg" else 1):
                    try:
                        p = safe_join(folder, f.path)
                    except PathNotAllowed:
                        continue
                    if p.is_file():
                        out.append(p)
                        break
            return out

        return await asyncio.to_thread(pick)

    # ---- start -----------------------------------------------------------------------
    async def start(self, session_id: str, req: RenderRequest) -> Job:
        """Validate, then submit the render job. Raises FeatureUnsupported (no ffmpeg),
        SessionNotFound, InvalidState (no usable frames), CameraBusy (already rendering)."""
        ffmpeg = self._require_ffmpeg()
        manifest = await self._sessions.get(session_id)
        frames = await self._select_frames(session_id, req.bracket_frame)
        if not frames:
            raise InvalidState(
                "This session has no usable frames to render", details={"session_id": session_id}
            )
        v = self._config.config.video
        opts = resolve_options(
            req, cfg_codec=v.codec, cfg_crf=v.crf, cfg_preset=v.preset, cfg_fps=v.fps
        )
        name = output_filename(req.output_name, f"timelapse_{manifest.id}", opts.codec)

        async def factory(ctx: JobContext) -> dict[str, Any]:
            return await self._render(ctx, ffmpeg, session_id, frames, opts, name)

        return self._jobs.submit("render-video", factory, exclusive_key=f"render:{session_id}")

    # ---- job body --------------------------------------------------------------------
    async def _render(
        self,
        ctx: JobContext,
        ffmpeg: str,
        session_id: str,
        frames: list[Path],
        opts: RenderOptions,
        name: str,
    ) -> dict[str, Any]:
        work = self._tmp_root / uuid.uuid4().hex
        final: Path | None = None
        part: Path | None = None
        ok = False
        try:
            ctx.report(0.0, "Preparing frames")
            count = await asyncio.to_thread(prepare_sequence, frames, work)
            if count == 0:
                raise InvalidState("None of the session's frames could be read")
            videos_dir = self._sessions.folder(session_id) / "videos"
            final = await asyncio.to_thread(unique_path, videos_dir, name)
            part = final.with_name(f"{final.stem}.part{final.suffix}")
            argv = build_ffmpeg_args(ffmpeg, str(work / "%06d.jpg"), str(part), opts)
            ctx.report(0.0, "Encoding")
            await self._run_ffmpeg(ctx, argv, count)
            if not part.is_file() or part.stat().st_size == 0:
                raise RenderFailed("ffmpeg produced no output")
            await asyncio.to_thread(os.replace, part, final)
            size = final.stat().st_size
            await self._sessions.add_video(
                session_id,
                SessionVideo(
                    name=final.name,
                    created=datetime.now(UTC),
                    size=size,
                    fps=opts.fps,
                    codec=opts.codec,
                ),
            )
            ok = True
            return {
                "session_id": session_id,
                "name": final.name,
                "path": f"sessions/{session_id}/videos/{final.name}",
                "size": size,
                "frames": count,
            }
        finally:
            await asyncio.to_thread(shutil.rmtree, work, True)
            if not ok:
                for p in (part, final):
                    if p is not None:
                        with contextlib.suppress(OSError):
                            p.unlink(missing_ok=True)

    async def _run_ffmpeg(self, ctx: JobContext, argv: list[str], total: int) -> None:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        tail: collections.deque[str] = collections.deque(maxlen=40)

        async def read_stderr() -> None:
            async for raw in proc.stderr or _EMPTY:
                tail.append(raw.decode(errors="replace").rstrip())

        async def read_stdout() -> None:
            async for raw in proc.stdout or _EMPTY:
                n = parse_progress_line(raw.decode(errors="replace").strip())
                if n is not None and total:
                    ctx.report(min(0.99, n / total), f"Encoded {min(n, total)}/{total} frames")

        timeout = self._base_timeout + total * self._per_frame
        stderr_task = asyncio.create_task(read_stderr())
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(read_stdout(), proc.wait())
                await stderr_task
        except TimeoutError:
            await self._stop(proc)
            raise RenderFailed(f"ffmpeg timed out after {timeout:.0f}s") from None
        except BaseException:
            await self._stop(proc)
            raise
        finally:
            stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stderr_task
        if proc.returncode != 0:
            msg = "\n".join(tail)[-STDERR_TAIL_CHARS:]
            raise RenderFailed(
                f"ffmpeg exited with code {proc.returncode}: {msg}".strip(),
                details={"exit_code": proc.returncode},
            )

    async def _stop(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), self._grace)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    # ---- library ---------------------------------------------------------------------
    def _entry(self, session_id: str, v: SessionVideo) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "name": v.name,
            "path": f"sessions/{session_id}/videos/{v.name}",
            "size": v.size,
            "created": v.created,
            "fps": v.fps,
            "codec": v.codec,
        }

    async def list_videos(self, session_id: str | None = None) -> list[dict[str, Any]]:
        if session_id is not None:
            ids = [self._sessions.validate_id(session_id)]
        else:
            ids = [s.id for s in await self._sessions.list() if s.video_count and not s.corrupt]
        out: list[dict[str, Any]] = []
        for sid in ids:
            try:
                m = await self._sessions.get(sid)
            except SessionNotFound:
                if session_id is not None:
                    raise
                continue
            out.extend(self._entry(sid, v) for v in m.videos)
        out.sort(key=lambda e: e["created"], reverse=True)
        return out

    async def video_path(self, session_id: str, name: str) -> Path:
        """Contained absolute path of a manifest-listed video (404 otherwise)."""
        if name != sanitize_name(name, default=""):
            raise PathNotAllowed("Invalid video name")
        m = await self._sessions.get(session_id)
        if not any(v.name == name for v in m.videos):
            raise FileNotFoundError_("Video not found")
        path = safe_join(self._sessions.folder(session_id) / "videos", name)
        if not await asyncio.to_thread(path.is_file):
            raise FileNotFoundError_("Video file is missing")
        return path

    async def delete_video(self, session_id: str, name: str) -> None:
        if name != sanitize_name(name, default=""):
            raise PathNotAllowed("Invalid video name")
        m = await self._sessions.get(session_id)
        if not any(v.name == name for v in m.videos):
            raise FileNotFoundError_("Video not found")
        path = safe_join(self._sessions.folder(session_id) / "videos", name)
        await asyncio.to_thread(path.unlink, True)
        await self._sessions.remove_video(session_id, name)
