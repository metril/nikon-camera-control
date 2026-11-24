"""Local output-directory file index (cached) and delete helper."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.core.errors import FileNotFoundError_, PathNotAllowed
from backend.core.storage_root import StorageRoot, as_root
from backend.services import integrity
from backend.services.storage import MediaKindName, classify, safe_join
from backend.services.thumbnails import DEFAULT_SIZE, ThumbnailService

KindFilter = Literal["image", "raw", "video", "all"]
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
            f
            for f in files
            if (not folder or f.path.startswith(prefix)) and (kind == "all" or f.kind == kind)
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


class FileService:
    def __init__(self, store: Path | StorageRoot, thumb_size: Any = None) -> None:
        self._store = as_root(store)
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
