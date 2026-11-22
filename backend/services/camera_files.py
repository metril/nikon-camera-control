"""Files on the camera card: cached listing, single download/delete, download-all job.

No FastAPI imports. All camera access goes through ``CameraService.call``.

Priorities: listing and downloads run at KEEPALIVE priority (below control/capture, above
live view) and are NOT blocked by a camera lease; delete runs at CONTROL so another owner's
lease yields 409.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.api.schemas.common import EventType
from backend.camera.backend import CameraFileInfo, CameraFilePath, FileKind
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import AppError, CameraNotConnected, PathNotAllowed
from backend.core.events import EventBus, Subscription
from backend.core.jobs import Job, JobContext, JobManager
from backend.services.storage import download_files

if TYPE_CHECKING:
    from backend.api.schemas.camera_files import CameraFileEntry, DownloadAllRequest

log = logging.getLogger(__name__)

_MAX_DEPTH = 8
_LIST_TIMEOUT_S = 30.0
_READ_TIMEOUT_S = 600.0
_NAME_CAP = 50  # max file names echoed in a job result
_INVALIDATING = frozenset(
    {
        EventType.CAPTURE_COMPLETE,
        EventType.CAMERA_CONNECTED,
        EventType.CAMERA_DISCONNECTED,
        EventType.TIMELAPSE_FRAME,
        EventType.RECORDING_STOPPED,
    }
)
_RAW = frozenset({".nef", ".nrw", ".dng", ".cr2", ".cr3", ".arw", ".raf"})
_VIDEO = frozenset({".mov", ".mp4", ".avi", ".mkv"})


def validate_camera_folder(folder: str) -> str:
    """Absolute camera path without NUL, ``..`` or empty-segment tricks; normalised."""
    if not folder or "\0" in folder or "\\" in folder or not folder.startswith("/"):
        raise PathNotAllowed("Folder must be an absolute camera path", details={"folder": folder})
    parts = [p for p in folder.split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise PathNotAllowed("Folder must not contain '.' or '..'", details={"folder": folder})
    return "/" + "/".join(parts)


def validate_camera_name(name: str) -> str:
    if not name or "\0" in name or "/" in name or "\\" in name or name in (".", ".."):
        raise PathNotAllowed("Invalid file name", details={"name": name})
    return name


def join_camera_path(folder: str, name: str) -> str:
    return f"{folder.rstrip('/')}/{name}"


def file_type(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "jpeg"
    if ext in _RAW:
        return "raw"
    if ext in _VIDEO:
        return "video"
    return "other"


_Key = tuple[str, str, int, float]


class DownloadLedger:
    """Persistent set of downloaded files keyed by (folder, name, size, mtime)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._keys: set[_Key] | None = None

    def _load(self) -> set[_Key]:
        if self._keys is None:
            keys: set[_Key] = set()
            try:
                raw = json.loads(self._path.read_text())
                for f, n, s, m in raw.get("entries", []):
                    keys.add((str(f), str(n), int(s), float(m)))
            except FileNotFoundError:
                pass
            except (ValueError, TypeError, AttributeError, OSError):
                log.warning("download ledger %s unreadable; starting empty", self._path)
            self._keys = keys
        return self._keys

    def _save(self) -> None:
        data = json.dumps({"version": 1, "entries": [list(k) for k in sorted(self._load())]})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".downloaded-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    @staticmethod
    def key(info: CameraFileInfo) -> _Key:
        return (info.folder, info.name, info.size, info.mtime)

    async def load(self) -> None:
        await asyncio.to_thread(self._load)

    def has(self, info: CameraFileInfo) -> bool:
        """Cheap in-memory check; call ``load()`` first."""
        return self._keys is not None and self.key(info) in self._keys

    async def add(self, info: CameraFileInfo) -> None:
        def _do() -> None:
            self._load().add(self.key(info))
            self._save()

        await asyncio.to_thread(_do)


@dataclass
class _Cache:
    gen: int = 0
    folders: dict[str, list[str]] = field(default_factory=dict)
    files: dict[str, list[CameraFileInfo]] = field(default_factory=dict)

    def reset(self) -> None:
        self.gen += 1
        self.folders = {}
        self.files = {}


class CameraFilesService:
    def __init__(
        self,
        camera: CameraService,
        bus: EventBus,
        jobs: JobManager,
        data_dir: Path,
        output_dir: Path,
    ) -> None:
        self._camera = camera
        self._bus = bus
        self._jobs = jobs
        self._data_dir = data_dir
        self._dest = output_dir / "camera"
        self._ledger = DownloadLedger(data_dir / "downloaded.json")
        self._cache = _Cache()
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    # cache ----------------------------------------------------------------
    def invalidate(self) -> None:
        """Drop the cached listing (also done on capture/connect/disconnect events)."""
        self._cache.reset()

    def _ensure_listener(self) -> None:
        if self._task is None:
            self._sub = self._bus.subscribe()
            self._task = asyncio.get_running_loop().create_task(self._listen(self._sub))

    async def _listen(self, sub: Subscription) -> None:
        async for ev in sub:
            if ev.type in _INVALIDATING:
                self.invalidate()

    async def aclose(self) -> None:
        if self._sub is not None:
            self._sub.close()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    # listing --------------------------------------------------------------
    async def list_folders(self, folder: str) -> list[str]:
        self._ensure_listener()
        c = self._cache
        if folder in c.folders:
            return c.folders[folder]
        gen = c.gen
        names = await self._camera.call(
            lambda b: b.list_folders(folder), priority=Priority.KEEPALIVE, timeout=_LIST_TIMEOUT_S
        )
        if gen == c.gen:
            c.folders[folder] = names
        return names

    async def _folder_files(self, folder: str) -> list[CameraFileInfo]:
        self._ensure_listener()
        c = self._cache
        if folder in c.files:
            return c.files[folder]
        gen = c.gen
        infos = await self._camera.call(
            lambda b: b.list_files(folder), priority=Priority.KEEPALIVE, timeout=_LIST_TIMEOUT_S
        )
        if gen == c.gen:
            c.files[folder] = infos
        return infos

    async def _walk(self, folder: str, recursive: bool, depth: int = 0) -> list[CameraFileInfo]:
        # One camera call per folder so keepalive/live view interleave. Errors propagate.
        out = list(await self._folder_files(folder))
        if recursive and depth < _MAX_DEPTH:
            for name in await self.list_folders(folder):
                out += await self._walk(join_camera_path(folder, name), True, depth + 1)
        return out

    async def list_infos(self, folder: str, recursive: bool) -> list[CameraFileInfo]:
        infos = await self._walk(folder, recursive)
        infos.sort(key=lambda i: (i.folder, i.name))
        return infos

    async def list(self, folder: str = "/", recursive: bool = False) -> list[CameraFileEntry]:
        from backend.api.schemas.camera_files import CameraFileEntry

        infos = await self.list_infos(folder, recursive)
        await self._ledger.load()
        return [
            CameraFileEntry(
                folder=i.folder,
                name=i.name,
                size=i.size,
                mtime=i.mtime,
                type=file_type(i.name),  # type: ignore[arg-type]
                downloaded=self._ledger.has(i),
            )
            for i in infos
        ]

    # single file ----------------------------------------------------------
    async def fetch_to_temp(self, folder: str, name: str) -> tuple[Path, Path]:
        """Stream one file to a fresh temp dir under the data dir; returns (dir, file)."""
        tmp_root = self._data_dir / "tmp"

        def _mk() -> Path:
            tmp_root.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(dir=tmp_root))

        tmp_dir = await asyncio.to_thread(_mk)
        dest = tmp_dir / name
        try:
            await self._camera.call(
                lambda b: b.read_file(folder, name, FileKind.NORMAL, dest),
                priority=Priority.KEEPALIVE,
                timeout=_READ_TIMEOUT_S,
            )
        except BaseException:
            await asyncio.to_thread(_rm, tmp_dir)
            raise
        return tmp_dir, dest

    async def delete(self, folder: str, name: str) -> None:
        try:
            await self._camera.call(
                lambda b: b.delete_file(folder, name), priority=Priority.CONTROL, timeout=30.0
            )
        finally:
            self.invalidate()

    # download-all job -----------------------------------------------------
    def start_download_all(self, req: DownloadAllRequest) -> Job:
        return self._jobs.submit(
            "download_all", lambda ctx: self._download_all(ctx, req), exclusive_key="download-all"
        )

    async def _download_all(self, ctx: JobContext, req: DownloadAllRequest) -> dict[str, Any]:
        # Deliberately NO camera lease: a lease would block captures for the whole job.
        # Trade-off: a capture/timelapse may interleave between files (each file is one
        # worker call), and a lease holder makes individual files fail with CameraBusy.
        # Files go strictly one at a time: concurrency over a single USB link buys nothing.
        ctx.report(0.0, "Listing files")
        self.invalidate()
        infos = await self.list_infos(req.folder or "/", True)
        await self._ledger.load()
        todo = [i for i in infos if not (req.only_new and self._ledger.has(i))]
        skipped = len(infos) - len(todo)
        downloaded = 0
        failed: list[str] = []
        got: list[str] = []
        n_failed = 0
        await asyncio.to_thread(self._dest.mkdir, parents=True, exist_ok=True)
        try:
            for idx, info in enumerate(todo, start=1):
                if ctx.cancelled:
                    break
                ctx.report(
                    (idx - 1) / len(todo),
                    f"{info.name} ({idx}/{len(todo)}); {downloaded} done, {n_failed} failed",
                )
                try:
                    await download_files(
                        self._camera,
                        [CameraFilePath(info.folder, info.name)],
                        self._dest,
                        delete_from_camera=req.delete_after,
                    )
                except CameraNotConnected:
                    raise
                except AppError as exc:
                    log.warning("download of %s failed: %s", info.name, exc.message)
                    n_failed += 1
                    if len(failed) < _NAME_CAP:
                        failed.append(info.name)
                    continue
                downloaded += 1
                if len(got) < _NAME_CAP:
                    got.append(info.name)
                await self._ledger.add(info)
        finally:
            if req.delete_after:
                self.invalidate()
        return {
            "folder": req.folder or "/",
            "total": len(infos),
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": n_failed,
            "downloaded_names": got,
            "failed_names": failed,
            "cancelled": ctx.cancelled,
        }


def _rm(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
