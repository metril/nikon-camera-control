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
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.api.schemas.common import EventType
from backend.camera.backend import CameraFileInfo, CameraFilePath, FileKind
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import (
    AppError,
    CameraNotConnected,
    CameraOperationFailed,
    FileNotFoundError_,
    NoTargetError,
    PathNotAllowed,
)
from backend.core.events import EventBus, Subscription
from backend.core.jobs import Job, JobContext, JobManager
from backend.core.storage_root import StorageRoot, as_root
from backend.services.storage import download_files

if TYPE_CHECKING:
    from collections.abc import Callable

    from backend.api.schemas.camera_files import CameraFileEntry, DownloadAllRequest

log = logging.getLogger(__name__)

_MAX_DEPTH = 8
_LIST_TIMEOUT_S = 30.0
_INFO_BATCH = 50  # file infos fetched per camera call (about 1.5 s on a D500)
_READ_TIMEOUT_S = 600.0
_TMP_MAX_AGE_S = 3600.0  # single-file download temp dirs older than this are removed
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


def _infos(b: Any, folder: str, names: list[str]) -> list[CameraFileInfo]:
    out: list[CameraFileInfo] = []
    for n in names:
        try:
            out.append(b.file_info(folder, n))
        except FileNotFoundError_:
            continue  # deleted (e.g. on the body) between the name listing and now
        except CameraOperationFailed as e:
            # e.g. leftover RAM-capture entries at "/" that cannot be stat'ed: skip, never fail
            log.warning("skipping %s/%s in listing: %s", folder, n, e.message)
    return out


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
    """Persistent set of downloaded files keyed by (folder, name, size, mtime).

    Stored as append-only JSONL (one ``[folder, name, size, mtime]`` line per file), so
    recording a download is O(1) on disk; lookups are O(1) in memory. A torn last line is
    ignored (and repaired by the next append). A legacy ``downloaded.json`` next to the
    ledger is migrated on first load.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._legacy = path.with_suffix(".json")
        self._keys: set[_Key] | None = None

    @staticmethod
    def _parse(raw: Any) -> _Key:
        f, n, s, m = raw
        return (str(f), str(n), int(s), float(m))

    def _load(self) -> set[_Key]:
        if self._keys is not None:
            return self._keys
        keys: set[_Key] = set()
        try:
            with open(self._path, "rb") as fh:
                for line in fh:
                    try:
                        keys.add(self._parse(json.loads(line)))
                    except (ValueError, TypeError):
                        log.warning("skipping unreadable line in download ledger %s", self._path)
        except FileNotFoundError:
            self._migrate_legacy(keys)
        except OSError:
            log.warning("download ledger %s unreadable; starting empty", self._path)
        self._keys = keys
        return keys

    def _migrate_legacy(self, keys: set[_Key]) -> None:
        if self._legacy == self._path:
            return
        try:
            raw = json.loads(self._legacy.read_text())
            entries = [self._parse(e) for e in raw.get("entries", [])]
        except FileNotFoundError:
            return
        except (ValueError, TypeError, AttributeError, OSError):
            log.warning("legacy download ledger %s unreadable; ignoring", self._legacy)
            return
        keys.update(entries)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".downloaded-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                for k in sorted(keys):
                    fh.write(json.dumps(list(k)) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
            self._legacy.rename(self._legacy.with_name(self._legacy.name + ".migrated"))
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            log.warning("could not migrate legacy download ledger %s", self._legacy)

    def _append(self, key: _Key) -> None:
        line = json.dumps(list(key)).encode() + b"\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "ab+") as fh:
            if fh.tell() > 0:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    line = b"\n" + line  # repair a torn last line
            fh.write(line)

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
            keys = self._load()
            k = self.key(info)
            if k not in keys:
                self._append(k)
                keys.add(k)

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
        store: Path | StorageRoot,
    ) -> None:
        self._camera = camera
        self._bus = bus
        self._jobs = jobs
        self._store = as_root(store)
        self._ledgers: dict[Path, DownloadLedger] = {}
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
        """Files of one folder: one cheap call for the names, then the per-file info in small
        batches (one camera call each), so a card with thousands of files never holds the
        camera for the whole listing and keepalive/live view/captures interleave."""
        self._ensure_listener()
        c = self._cache
        if folder in c.files:
            return c.files[folder]
        gen = c.gen
        try:
            names = await self._camera.call(
                lambda b: b.list_file_names(folder),
                priority=Priority.KEEPALIVE,
                timeout=_LIST_TIMEOUT_S,
            )
        except CameraOperationFailed:
            if folder == "/":  # the root only holds the storage folders; some bodies refuse it
                return []
            raise
        infos: list[CameraFileInfo] = []
        for i in range(0, len(names), _INFO_BATCH):
            chunk = names[i : i + _INFO_BATCH]
            infos += await self._camera.call(
                lambda b, chunk=chunk: _infos(b, folder, chunk),  # type: ignore[misc]
                priority=Priority.KEEPALIVE,
                timeout=_LIST_TIMEOUT_S,
            )
        if gen == c.gen:
            c.files[folder] = infos
        return infos

    async def _walk(
        self,
        folder: str,
        recursive: bool,
        depth: int = 0,
        on_found: Callable[[int], None] | None = None,
        found: list[int] | None = None,
    ) -> list[CameraFileInfo]:
        # One camera call per folder so keepalive/live view interleave. Errors propagate.
        found = found if found is not None else [0]
        out = list(await self._folder_files(folder))
        found[0] += len(out)
        if on_found is not None:
            on_found(found[0])
        if recursive and depth < _MAX_DEPTH:
            for name in await self.list_folders(folder):
                out += await self._walk(
                    join_camera_path(folder, name), True, depth + 1, on_found, found
                )
        return out

    async def list_infos(
        self, folder: str, recursive: bool, on_found: Callable[[int], None] | None = None
    ) -> list[CameraFileInfo]:
        infos = await self._walk(folder, recursive, on_found=on_found)
        infos.sort(key=lambda i: (i.folder, i.name))
        return infos

    async def list(self, folder: str = "/", recursive: bool = False) -> list[CameraFileEntry]:
        from backend.api.schemas.camera_files import CameraFileEntry

        infos = await self.list_infos(folder, recursive)
        ledger: DownloadLedger | None
        try:  # without a target nothing counts as downloaded
            ledger = self._ledger
        except NoTargetError:
            ledger = None
        if ledger is not None:
            await ledger.load()
        return [
            CameraFileEntry(
                folder=i.folder,
                name=i.name,
                size=i.size,
                mtime=i.mtime,
                type=file_type(i.name),  # type: ignore[arg-type]
                downloaded=ledger is not None and ledger.has(i),
            )
            for i in infos
        ]

    @property
    def _ledger(self) -> DownloadLedger:
        """The download ledger of the current target (``<target>/.ncc/downloaded.jsonl``)."""
        path = self._store.cache() / "downloaded.jsonl"
        ledger = self._ledgers.get(path)
        if ledger is None:
            self._ledgers.clear()
            ledger = self._ledgers[path] = DownloadLedger(path)
        return ledger

    # single file ----------------------------------------------------------
    async def fetch_to_temp(self, folder: str, name: str) -> tuple[Path, Path]:
        """Stream one file to a fresh temp dir under the data dir; returns (dir, file)."""
        tmp_root = self._store.cache() / "tmp"

        def _mk() -> Path:
            tmp_root.mkdir(parents=True, exist_ok=True)
            _sweep_stale_dirs(tmp_root, _TMP_MAX_AGE_S)  # leftovers of dropped downloads
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

    async def fetch_preview(self, folder: str, name: str) -> bytes:
        """The camera's embedded preview JPEG of one file (needs no storage target)."""
        tmp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="ncc-thumb-"))
        dest = tmp_dir / "preview.jpg"
        try:
            await self._camera.call(
                lambda b: b.read_file(folder, name, FileKind.PREVIEW, dest),
                priority=Priority.PREVIEW,  # lowest: never ahead of live view frames
                timeout=_READ_TIMEOUT_S,
            )
            return await asyncio.to_thread(dest.read_bytes)
        finally:
            await asyncio.to_thread(_rm, tmp_dir)

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
        ctx.report(None, "Listing files")
        self.invalidate()
        infos = await self.list_infos(
            req.folder or "/",
            True,
            lambda n: ctx.report(None, f"Listing files ({n} files so far)"),
        )
        ledger = self._ledger
        await ledger.load()
        dest = self._store.root() / "camera"
        todo = [i for i in infos if not (req.only_new and ledger.has(i))]
        skipped = len(infos) - len(todo)
        downloaded = 0
        failed: list[str] = []
        got: list[str] = []
        n_failed = 0
        await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)

        def _result() -> dict[str, Any]:
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

        try:
            for idx, info in enumerate(todo, start=1):
                if ctx.cancelled:
                    break
                ctx.report(
                    (idx - 1) / len(todo),
                    f"{info.name} ({idx}/{len(todo)}); {downloaded} done, {n_failed} failed",
                )
                # Shielded: a cancel waits for the in-flight file (its worker thread cannot be
                # interrupted) so its .part is renamed or removed by download_files, never leaked.
                task = asyncio.ensure_future(
                    download_files(
                        self._camera,
                        [CameraFilePath(info.folder, info.name)],
                        dest,
                        delete_from_camera=req.delete_after,
                        on_stored=self._store.stored,
                    )
                )
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await asyncio.gather(task, return_exceptions=True)
                    if not task.cancelled() and task.exception() is None:
                        downloaded += 1
                        if len(got) < _NAME_CAP:
                            got.append(info.name)
                        await ledger.add(info)
                    ctx._cancel_requested = True
                    ctx.set_partial_result(_result())
                    raise
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
                await ledger.add(info)
        finally:
            if req.delete_after:
                self.invalidate()
        return _result()


def _rm(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _sweep_stale_dirs(root: Path, max_age_s: float) -> None:
    cutoff = time.time() - max_age_s
    for d in root.iterdir():
        with contextlib.suppress(OSError):
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
