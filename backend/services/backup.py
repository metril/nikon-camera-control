"""Stateless backup sync and verified offload.

A run walks the source (target) tree and, for every online backup, copies what is missing or
differs: copy to ``<name>.ncc-partial``, re-hash the partial, rename into place, record the
hash in the backup's own ``SHA256SUMS`` (+ sidecar). Nothing is persisted: after a restart, an
unplug or an outage the next run resumes from whatever is already on the backup.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from backend.api.schemas.common import EventType
from backend.core.config_store import ConfigStore
from backend.core.events import EventBus
from backend.services import integrity

log = logging.getLogger(__name__)

Progress = Callable[[int, int, int, str | None], None]  # copied, failed, pending, current


class IntegrityError(Exception):
    """A copy did not hash to what the source hashes to."""


@dataclass
class SyncReport:
    copied: int = 0
    skipped: int = 0  # already at the destination
    vetoed: int = 0  # left alone because the caller's skip() refused them
    failed: list[tuple[str, str]] = field(default_factory=list)
    deleted_source: int = 0
    cancelled: bool = False


def clean_partials_in(directory: Path) -> int:
    """Delete stale ``*.ncc-partial`` files directly in ``directory`` (not recursive)."""
    n = 0
    try:
        with os.scandir(directory) as it:
            names = [e.name for e in it if e.name.endswith(integrity.PARTIAL_EXT)]
    except OSError:
        return 0
    for name in names:
        with contextlib.suppress(OSError):
            os.unlink(directory / name)
            n += 1
    return n


_dest_locks: dict[str, asyncio.Lock] = {}


def dest_lock(root: Path) -> asyncio.Lock:
    """One lock per destination root, shared by backup runs and offload jobs, so one never
    cleans up or races the other's in-flight partial files. Event loop only."""
    return _dest_locks.setdefault(str(root), asyncio.Lock())


class _SumsCache:
    """Parsed SHA256SUMS per directory for one run. ``clean`` also removes stale partials
    from each directory the first time it is touched."""

    def __init__(self, clean: bool = False) -> None:
        self._clean = clean
        self._m: dict[Path, dict[str, str]] = {}

    def get(self, directory: Path) -> dict[str, str]:
        sums = self._m.get(directory)
        if sums is None:
            if self._clean:
                clean_partials_in(directory)
            sums = self._m[directory] = integrity.read_sums(directory)
        return sums


def copy_verified(
    src: Path,
    dst: Path,
    *,
    sidecars: bool,
    expected: str | None = None,
    cancel: threading.Event | None = None,
) -> str:
    """Copy ``src`` to ``dst`` through a partial file; both sides are hashed. Returns the
    SHA-256. Raises ``IntegrityError`` (partial removed) on any mismatch."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + integrity.PARTIAL_EXT)
    h = hashlib.sha256()
    try:
        with open(src, "rb") as fi:  # FileNotFoundError here means the source is gone
            try:
                with open(part, "wb") as fo:
                    while chunk := fi.read(integrity.CHUNK):
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError("cancelled")
                        h.update(chunk)
                        fo.write(chunk)
                    fo.flush()
                    os.fsync(fo.fileno())
            except FileNotFoundError as exc:  # the destination directory/partial vanished
                raise IntegrityError(f"partial copy of {src.name} disappeared") from exc
        src_hash = h.hexdigest()
        if expected is not None and expected != src_hash:
            raise IntegrityError(f"source {src.name} does not match its SHA256SUMS entry")
        try:
            if integrity.sha256_file(part, cancel) != src_hash:
                raise IntegrityError(f"copy of {src.name} does not match the source")
            st = src.stat()
            os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns))
            os.replace(part, dst)
        except FileNotFoundError as exc:
            if not part.exists():
                raise IntegrityError(f"partial copy of {src.name} disappeared") from exc
            raise  # the source vanished at the very end
    except BaseException:
        with contextlib.suppress(OSError):
            part.unlink()
        raise
    integrity.record(dst, sidecar=sidecars, digest=src_hash)
    return src_hash


def _src_hash(src: Path, sums: dict[str, str]) -> str:
    return sums.get(src.name) or integrity.sha256_file(src)


def _needs_copy(
    src: Path,
    dst: Path,
    src_sums: dict[str, str],
    dst_sums: dict[str, str],
    deep: bool,
    sidecars: bool,
) -> bool:
    """``dst_sums`` is the (cached, mutable) parsed SHA256SUMS of ``dst``'s directory."""
    try:
        dst_size = dst.stat().st_size
    except OSError:
        return True
    if dst_size != src.stat().st_size:
        return True
    want = _src_hash(src, src_sums)
    listed = dst_sums.get(dst.name)
    if listed is None or deep:
        have = integrity.sha256_file(dst)  # unlisted (hand-copied) or deep mode
        if have != want:
            return True
        if listed is None:
            integrity.record(dst, sidecar=sidecars, digest=have)
            dst_sums[dst.name] = have
        return False
    return listed != want


def sync_file(
    src: Path,
    dst: Path,
    *,
    sidecars: bool,
    deep: bool,
    cancel: threading.Event | None = None,
    force_verify: bool = False,
    src_sums: dict[str, str] | None = None,
    dst_sums: dict[str, str] | None = None,
) -> Literal["copied", "skipped"]:
    """Copy ``src`` to ``dst`` unless ``dst`` already has the same size and hash.
    ``force_verify`` (offload) always re-hashes an existing destination. Pass the
    per-directory sums caches to avoid re-parsing SHA256SUMS for every file."""
    if src_sums is None:
        src_sums = integrity.read_sums(src.parent)
    if dst_sums is None:
        dst_sums = integrity.read_sums(dst.parent)
    if not _needs_copy(src, dst, src_sums, dst_sums, deep or force_verify, sidecars):
        return "skipped"
    for attempt in (1, 2):  # one retry: a flaky copy is detected, then retried once
        try:
            dst_sums[dst.name] = copy_verified(
                src, dst, sidecars=sidecars, expected=src_sums.get(src.name), cancel=cancel
            )
            return "copied"
        except IntegrityError:
            if attempt == 2:
                raise
            log.warning("verification failed for %s; retrying", dst)
    raise AssertionError("unreachable")


def sync_tree(
    src_root: Path,
    dst_root: Path,
    *,
    deep: bool,
    sidecars: bool,
    cancel: threading.Event | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    progress: Progress | None = None,
) -> SyncReport:
    rep = SyncReport()
    src_cache, dst_cache = _SumsCache(), _SumsCache(clean=True)

    def stop() -> bool:
        return (cancel is not None and cancel.is_set()) or should_stop()

    todo: list[Path] = []
    for src in integrity.iter_files(src_root):
        if stop():
            rep.cancelled = True
            return rep
        dst = dst_root / src.relative_to(src_root)
        try:
            if _needs_copy(
                src, dst, src_cache.get(src.parent), dst_cache.get(dst.parent), deep, sidecars
            ):
                todo.append(src)
            else:
                rep.skipped += 1
        except OSError:
            continue  # vanished while scanning: nothing to copy
    pending = len(todo)
    if progress:
        progress(0, 0, pending, None)
    for i, src in enumerate(todo):
        if stop():
            rep.cancelled = True
            break
        rel = src.relative_to(src_root)
        if progress:
            progress(rep.copied, len(rep.failed), pending - i, rel.as_posix())
        dst = dst_root / rel
        try:
            res = sync_file(
                src,
                dst,
                sidecars=sidecars,
                deep=deep,
                cancel=cancel,
                src_sums=src_cache.get(src.parent),
                dst_sums=dst_cache.get(dst.parent),
            )
        except FileNotFoundError:
            continue  # deleted from the target before it was copied: simply not copied
        except InterruptedError:
            rep.cancelled = True
            break
        except (OSError, IntegrityError) as exc:
            log.warning("backup of %s failed: %s", rel, exc)
            rep.failed.append((rel.as_posix(), str(exc)))
            continue
        if res == "copied":
            rep.copied += 1
        else:
            rep.skipped += 1
    if progress:
        progress(rep.copied, len(rep.failed), 0, None)
    return rep


def select_files(
    root: Path,
    scope: Literal["all", "session", "older_than"],
    *,
    session_id: str | None = None,
    before: datetime | None = None,
    exclude_sessions: frozenset[str] = frozenset(),
    min_age_s: float = 0.0,
) -> list[Path]:
    """Files to offload. ``exclude_sessions`` (active or held session ids) and files modified
    within ``min_age_s`` seconds (still being written) are left out."""
    if scope == "session":
        if not session_id or "/" in session_id or session_id.startswith("."):
            raise ValueError("invalid session id")
        files = list(integrity.iter_files(root, f"sessions/{session_id}"))
    else:
        files = list(integrity.iter_files(root))
    if scope == "older_than":
        if before is None:
            raise ValueError("'before' is required")
        cutoff = before.timestamp()
        files = [f for f in files if _mtime(f) < cutoff]
    if exclude_sessions:
        files = [f for f in files if session_of(f, root) not in exclude_sessions]
    if min_age_s > 0:
        newest = time.time() - min_age_s
        files = [f for f in files if _mtime(f) <= newest]
    return files


def session_of(path: Path, root: Path) -> str | None:
    parts = path.relative_to(root).parts
    return parts[1] if len(parts) > 2 and parts[0] == "sessions" else None


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return float("inf")


def offload_files(
    files: list[Path],
    src_root: Path,
    dst_root: Path,
    *,
    keep_source: bool,
    sidecars: bool,
    cancel: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
    skip: Callable[[Path], bool] | None = None,
) -> SyncReport:
    """Verified copy of ``files`` to ``dst_root`` and, unless ``keep_source``, deletion of
    each source file (+ sidecar + SHA256SUMS line) only after the destination re-hashed equal.
    ``skip(src)`` is asked right before each file (e.g. its session became active since the
    file list was taken); vetoed files are left alone and counted as vetoed."""
    rep = SyncReport()
    src_cache, dst_cache = _SumsCache(), _SumsCache(clean=True)
    for i, src in enumerate(files):
        if cancel is not None and cancel.is_set():
            rep.cancelled = True
            break
        rel = src.relative_to(src_root)
        if progress:
            progress(i, len(files))
        if skip is not None and skip(src):
            rep.vetoed += 1
            continue
        try:
            dst = dst_root / rel
            res = sync_file(
                src,
                dst,
                sidecars=sidecars,
                deep=True,
                cancel=cancel,
                force_verify=True,
                src_sums=src_cache.get(src.parent),
                dst_sums=dst_cache.get(dst.parent),
            )
            if res == "copied":
                rep.copied += 1
            else:
                rep.skipped += 1
            if not keep_source:
                src.unlink()  # forget only once the file is really gone
                integrity.forget(src)
                src_cache.get(src.parent).pop(src.name, None)
                rep.deleted_source += 1
                with contextlib.suppress(OSError):  # prune emptied directories
                    p = src.parent
                    while p != src_root and not any(p.iterdir()):
                        p.rmdir()
                        p = p.parent
        except FileNotFoundError:
            continue
        except InterruptedError:
            rep.cancelled = True
            break
        except (OSError, IntegrityError) as exc:
            log.warning("offload of %s failed: %s", rel, exc)
            rep.failed.append((rel.as_posix(), str(exc)))
    return rep


@dataclass
class BackupStatus:
    running: bool = False
    pending: int = 0
    copied: int = 0
    failed: int = 0
    current: str | None = None
    last_run: datetime | None = None
    last_error: str | None = None
    backups_online: list[str] = field(default_factory=list)
    source_id: str | None = None


class BackupService:
    """Schedules ``sync_tree`` runs: debounced after each stored file, periodic, when a
    backup comes online, and on demand. One run at a time; a trigger during a run re-runs."""

    def __init__(
        self,
        store: ConfigStore,
        bus: EventBus,
        source: Callable[[], tuple[str, Path] | None],
        destinations: Callable[[], list[tuple[str, Path]]],
        *,
        debounce_s: float = 3.0,
    ) -> None:
        self._store = store
        self._bus = bus
        self._source = source
        self._destinations = destinations
        self._debounce = debounce_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancel = threading.Event()
        self._timer: asyncio.TimerHandle | None = None
        self._task: asyncio.Task[None] | None = None
        self._periodic: asyncio.Task[None] | None = None
        self._rerun = False
        self._closed = False
        self._last_pub = 0.0
        self.status = BackupStatus()

    # ---- scheduling ---------------------------------------------------------------------
    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._periodic = self._loop.create_task(self._periodic_loop(), name="backup-periodic")

    async def _periodic_loop(self) -> None:
        while True:
            await asyncio.sleep(self._store.config.storage.backup_interval_min * 60)
            self.run_now()

    def trigger(self) -> None:
        """Debounced run request. Thread-safe."""
        loop = self._loop
        if loop is None or self._closed:
            return
        loop.call_soon_threadsafe(self._arm)

    def _arm(self) -> None:
        if self._closed or self._loop is None:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._loop.call_later(self._debounce, self.run_now)

    def run_now(self) -> BackupStatus:
        """Start a run now (event loop only); if one is running, re-run when it ends."""
        if self._closed or self._loop is None:
            return self.status
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._task is not None and not self._task.done():
            self._rerun = True
        else:
            self._task = self._loop.create_task(self._run(), name="backup-run")
        return self.status

    async def aclose(self) -> None:
        self._closed = True
        self._cancel.set()
        if self._timer is not None:
            self._timer.cancel()
        for t in (self._periodic, self._task):
            if t is not None:
                t.cancel()
        await asyncio.gather(
            *(t for t in (self._periodic, self._task) if t), return_exceptions=True
        )

    # ---- run ----------------------------------------------------------------------------
    def _publish(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pub < 0.25:
            return
        self._last_pub = now
        s = self.status
        self._bus.publish(
            EventType.BACKUP_STATUS,
            {
                "running": s.running,
                "pending": s.pending,
                "copied": s.copied,
                "failed": s.failed,
                "current": s.current,
            },
        )

    async def _run(self) -> None:
        while True:
            self._rerun = False
            src = self._source()
            dests = self._destinations()
            st = self.status
            st.source_id = src[0] if src else None
            st.backups_online = [d[0] for d in dests]
            if src is None or not dests:
                st.running = False
                st.pending = 0
                self._publish(True)
                return
            st.running, st.copied, st.failed, st.last_error = True, 0, 0, None
            self._publish(True)
            cfg = self._store.config.storage
            base_copied = base_failed = 0
            for dst_id, dst_root in dests:

                def progress(
                    c: int,
                    f: int,
                    p: int,
                    cur: str | None,
                    bc: int = base_copied,
                    bf: int = base_failed,
                ) -> None:
                    s = self.status
                    s.copied, s.failed, s.pending, s.current = bc + c, bf + f, p, cur
                    self._publish()

                def stop(sid: str = src[0]) -> bool:
                    now = self._source()
                    return self._closed or now is None or now[0] != sid

                try:
                    async with dest_lock(dst_root):
                        rep = await asyncio.to_thread(
                            sync_tree,
                            src[1],
                            dst_root,
                            deep=cfg.deep_verify,
                            sidecars=cfg.sidecars,
                            cancel=self._cancel,
                            should_stop=stop,
                            progress=progress,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("backup to %s failed", dst_id)
                    st.last_error = f"{dst_id}: {exc}"
                    continue
                base_copied += rep.copied
                base_failed += len(rep.failed)
                if rep.failed:
                    st.last_error = f"{dst_id}: {rep.failed[0][0]}: {rep.failed[0][1]}"
            st.running, st.pending, st.current = False, 0, None
            st.last_run = datetime.now(UTC)
            self._publish(True)
            if not self._rerun or self._closed:
                return
