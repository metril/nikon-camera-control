"""Local output-directory file index (cached) and delete helper."""

from __future__ import annotations

import asyncio
import contextlib
import os
import queue
import secrets
import threading
import time
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.core.errors import AppError, FileNotFoundError_, PathNotAllowed
from backend.core.storage_root import StorageRoot, as_root
from backend.services import integrity
from backend.services.integrity import is_aux
from backend.services.storage import MediaKindName, classify, safe_join
from backend.services.thumbnails import DEFAULT_SIZE, ThumbnailService

KindFilter = Literal["image", "raw", "video", "photos", "all"]  # photos = image + raw
SortOrder = Literal["newest", "oldest", "name"]
_THUMB_KINDS = ("image", "raw")


@dataclass(frozen=True, slots=True)
class IndexedFile:
    path: str  # relative to the output root, "/" separated
    name: str
    folder: str  # relative parent ("" for the root)
    size: int
    modified: float
    kind: MediaKindName

    @property
    def has_thumbnail(self) -> bool:
        return self.kind in _THUMB_KINDS


@dataclass(frozen=True, slots=True)
class Listing:
    items: list[IndexedFile]
    total: int
    folders: list[str]  # immediate sub-folders (relative paths)


def _hidden(name: str) -> bool:
    return integrity.is_aux(name)


def _wanted(want: str, kind: str) -> bool:
    return want == "all" or kind == want or (want == "photos" and kind in ("image", "raw"))


class FileIndex:
    """In-memory recursive index of the output root.

    Rebuilt when ``invalidate()`` is called or any directory's mtime changed (one stat per
    directory, none per file, on a cache hit).
    """

    def __init__(self, root: Path | StorageRoot | Callable[[], Path]) -> None:
        if isinstance(root, Path):
            fixed = root
            self._root_fn: Callable[[], Path] = lambda: fixed
        elif callable(root):
            self._root_fn = root
        else:
            self._root_fn = root.root
        self._root = Path()  # set on first snapshot
        self._lock = threading.Lock()
        self._files: list[IndexedFile] = []
        self._dirs: dict[str, int] = {}  # relative dir -> mtime_ns
        self._valid = False

    def invalidate(self) -> None:
        self._valid = False

    def _fresh(self) -> bool:
        if not self._valid:
            return False
        for rel, mtime in self._dirs.items():
            try:
                if (self._root / rel).stat().st_mtime_ns != mtime:
                    return False
            except OSError:
                return False
        return True

    def _scan(self) -> None:
        files: list[IndexedFile] = []
        dirs: dict[str, int] = {}
        stack = [""]
        while stack:
            rel = stack.pop()
            base = self._root / rel if rel else self._root
            try:
                dirs[rel] = base.stat().st_mtime_ns
                with os.scandir(base) as it:
                    entries = list(it)
            except OSError:
                dirs.pop(rel, None)
                continue
            for e in entries:
                if _hidden(e.name):
                    continue
                child = f"{rel}/{e.name}" if rel else e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(child)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        files.append(
                            IndexedFile(
                                child, e.name, rel, st.st_size, st.st_mtime, classify(e.name)
                            )
                        )
                except OSError:
                    continue
        self._files, self._dirs, self._valid = files, dirs, True

    def snapshot(self) -> tuple[list[IndexedFile], list[str]]:
        with self._lock:
            root = self._root_fn()  # NoTargetError when nothing is mounted
            if root != self._root:  # target switched: the old listing is another location's
                self._root, self._valid = root, False
            if not self._fresh():
                self._valid = False
                self._scan()
            return self._files, list(self._dirs)

    def list(
        self, folder: str, page: int, limit: int, kind: KindFilter, sort: SortOrder
    ) -> Listing:
        files, dirs = self.snapshot()
        prefix = f"{folder}/" if folder else ""
        sel = [
            f for f in files if (not folder or f.path.startswith(prefix)) and _wanted(kind, f.kind)
        ]
        if sort == "newest":
            sel.sort(key=lambda f: (-f.modified, f.path))
        elif sort == "oldest":
            sel.sort(key=lambda f: (f.modified, f.path))
        else:
            sel.sort(key=lambda f: (f.name.lower(), f.path))
        sub = sorted(
            d
            for d in dirs
            if d and d != folder and d.startswith(prefix) and "/" not in d[len(prefix) :]
        )
        start = (page - 1) * limit
        return Listing(sel[start : start + limit], len(sel), sub)


ZIP_TICKET_TTL_S = 60.0
_ZIP_MAX_TICKETS = 64
_ZIP_CHUNK = 1024 * 1024
_ZIP_QUEUE_DEPTH = 8
_END = object()
_Paths = list[str]
_Failures = list[tuple[str, str]]
_ZipItems = list[tuple[Path, str]]


class _QueueWriter:
    """Unseekable file-like sink for ``zipfile``: every write goes to a bounded queue.

    ``put`` blocks (with a timeout loop) when the consumer is slow, and raises
    ``InterruptedError`` once ``cancel`` is set (client went away).
    """

    def __init__(self, q: queue.Queue[Any], cancel: threading.Event) -> None:
        self._q, self._cancel, self._pos = q, cancel, 0

    def put(self, item: Any) -> None:
        while True:
            if self._cancel.is_set():
                raise InterruptedError
            try:
                self._q.put(item, timeout=0.25)
                return
            except queue.Full:
                continue

    def write(self, data: bytes | bytearray | memoryview) -> int:
        n = len(data)
        if n:
            self.put(bytes(data))
            self._pos += n
        return n

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:
        pass


def _zip_worker(
    items: list[tuple[Path, str]], q: queue.Queue[Any], cancel: threading.Event
) -> None:
    sink = _QueueWriter(q, cancel)
    try:
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:  # type: ignore[call-overload]
            for path, arc in items:
                try:
                    src = open(path, "rb")  # noqa: SIM115
                except FileNotFoundError:
                    continue  # removed after the ticket was issued
                with src:
                    info = zipfile.ZipInfo.from_file(path, arc)
                    info.compress_type = zipfile.ZIP_STORED
                    with zf.open(info, "w", force_zip64=True) as dst:
                        while chunk := src.read(_ZIP_CHUNK):
                            dst.write(chunk)
    except InterruptedError:
        pass  # consumer went away
    except BaseException as exc:  # surfaced to the response stream
        with contextlib.suppress(InterruptedError):
            sink.put(exc)
    with contextlib.suppress(InterruptedError):
        sink.put(_END)


@dataclass(frozen=True, slots=True)
class ZipPlan:
    """What a redeemed ticket downloads: one file as-is, or a streamed archive."""

    single: Path | None
    items: list[tuple[Path, str]]


class FileService:
    def __init__(self, store: Path | StorageRoot, thumb_size: Any = None) -> None:
        self._store = as_root(store)
        self._tickets: dict[str, tuple[float, list[str]]] = {}
        self._tickets_lock = threading.Lock()
        self.index = FileIndex(self._store)
        self.thumbnails = ThumbnailService(self._store.cache, thumb_size or (lambda: DEFAULT_SIZE))

    @property
    def root(self) -> Path:
        return self._store.root()

    async def list(
        self, folder: str, page: int, limit: int, kind: KindFilter, sort: SortOrder
    ) -> Listing:
        def run() -> Listing:
            rel = ""
            if folder.strip("/"):
                target = safe_join(self.root, folder.strip("/"))
                if not target.is_dir():
                    raise FileNotFoundError_("Folder not found")
                rel = target.relative_to(self.root.resolve()).as_posix()
            return self.index.list(rel, page, limit, kind, sort)

        return await asyncio.to_thread(run)

    def resolve_file(self, relative: str) -> Path:
        p = safe_join(self.root, relative)
        if not p.is_file():
            raise FileNotFoundError_()
        return p

    async def delete(self, relative: str) -> None:
        def run() -> None:
            p = safe_join(self.root, relative)
            if p == self.root.resolve() or p.is_dir():
                raise PathNotAllowed("Folders cannot be deleted here")
            try:
                p.unlink()
                integrity.forget(p)
            except FileNotFoundError:
                raise FileNotFoundError_() from None
            finally:
                self.index.invalidate()

        await asyncio.to_thread(run)

    async def delete_many(self, paths: _Paths) -> tuple[_Paths, _Failures]:
        """Delete each file; failures are reported per path, never abort the rest."""

        def run() -> tuple[_Paths, _Failures]:
            deleted: _Paths = []
            failed: _Failures = []
            try:
                for rel in dict.fromkeys(paths):
                    try:
                        p = safe_join(self.root, rel)
                        if p == self.root.resolve() or p.is_dir():
                            raise PathNotAllowed("Folders cannot be deleted here")
                        p.unlink()
                        integrity.forget(p)
                        deleted.append(rel)
                    except FileNotFoundError:
                        failed.append((rel, "File not found"))
                    except AppError as exc:
                        failed.append((rel, exc.message))
                    except OSError as exc:
                        failed.append((rel, exc.strerror or "Could not delete"))
            finally:
                self.index.invalidate()
            return deleted, failed

        return await asyncio.to_thread(run)

    # zip downloads -----------------------------------------------------------
    def _purge_tickets(self, now: float) -> None:
        for t in [t for t, (exp, _) in self._tickets.items() if exp <= now]:
            del self._tickets[t]

    def create_zip_ticket(self, paths: _Paths) -> str:
        """Validate every path (400 traversal, 404 missing) and issue a single-use ticket."""
        unique = list(dict.fromkeys(paths))
        for rel in unique:
            if is_aux(rel.rsplit("/", 1)[-1]):
                raise PathNotAllowed("Invalid path", details={"path": rel})
            self.resolve_file(rel)
        ticket = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._tickets_lock:
            self._purge_tickets(now)
            if len(self._tickets) >= _ZIP_MAX_TICKETS:
                del self._tickets[min(self._tickets, key=lambda t: self._tickets[t][0])]
            self._tickets[ticket] = (now + ZIP_TICKET_TTL_S, unique)
        return ticket

    def redeem_zip_ticket(self, ticket: str) -> ZipPlan:
        """Consume the ticket (a second use is 404) and resolve its files."""
        with self._tickets_lock:
            self._purge_tickets(time.monotonic())
            entry = self._tickets.pop(ticket, None)
        if entry is None:
            raise FileNotFoundError_("Download link expired or already used")
        items: _ZipItems = []
        for rel in entry[1]:
            try:
                items.append((self.resolve_file(rel), rel))
            except FileNotFoundError_:
                continue
        if not items:
            raise FileNotFoundError_()
        single = items[0][0] if len(entry[1]) == 1 else None
        return ZipPlan(single, items)

    @staticmethod
    async def stream_zip(items: _ZipItems) -> AsyncIterator[bytes]:
        """ZIP_STORED zip64 archive built in a worker thread, passed through a bounded queue."""
        q: queue.Queue[Any] = queue.Queue(_ZIP_QUEUE_DEPTH)
        cancel = threading.Event()
        worker = threading.Thread(
            target=_zip_worker, args=(items, q, cancel), name="zip-stream", daemon=True
        )
        worker.start()
        try:
            while True:
                item = await asyncio.to_thread(q.get)
                if item is _END:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            cancel.set()
