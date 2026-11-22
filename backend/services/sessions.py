"""Persistent time-lapse session store (the manifest contract for runner and video renderer).

Layout: ``<output_dir>/sessions/<id>/session.json`` (header + counters, small) and
``frames.jsonl`` (one ``SessionFrame`` JSON per line, append-only). Frame image files live
anywhere inside the session folder; ``SessionFile.path`` is relative to it.

Durability policy (``fsync=True`` by default): each frame line is appended and fsynced
(frames arrive seconds apart); header writes are tmp + fsync + ``os.replace``. To keep appends
cheap for 10,000-frame sessions the header's ``frames_captured`` is flushed only every
``header_flush_every`` frames and on every ``update``; after a crash the count may lag by less
than that, and ``recover_interrupted`` recounts it from ``frames.jsonl``. A torn last line is
ignored on read and repaired (newline-terminated) on the next append.

All mutating methods are serialised per session by an ``asyncio.Lock``; blocking IO runs via
``asyncio.to_thread``. ``get`` returns the header only (``frames == []``) unless
``with_frames=True``; page frames with ``list_frames`` / ``iter_frames``.
"""

from __future__ import annotations

import asyncio
import builtins
import json
import logging
import os
import re
import secrets
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from backend.api.schemas.sessions import (
    ACTIVE_STATUSES,
    SessionFrame,
    SessionManifest,
    SessionStatus,
    SessionSummary,
    SessionVideo,
)
from backend.core.errors import InvalidState, PathNotAllowed, SessionNotFound
from backend.services.storage import safe_join

log = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_HEADER = "session.json"
_FRAMES = "frames.jsonl"
_UPDATABLE = frozenset(
    {
        "name",
        "status",
        "config",
        "planned_frames",
        "frames_captured",
        "frames_failed",
        "started",
        "finished",
        "error",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    def __init__(
        self,
        output_dir: Path,
        *,
        fsync: bool = True,
        header_flush_every: int = 25,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._clock = clock
        self.root = Path(output_dir) / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync
        self._flush_every = max(1, header_flush_every)
        self._locks: dict[str, asyncio.Lock] = {}
        self._cache: dict[str, SessionManifest] = {}  # headers touched by this process
        self._unflushed: dict[str, int] = {}

    # ---- helpers -------------------------------------------------------------------------
    @staticmethod
    def validate_id(session_id: str) -> str:
        if not SESSION_ID_RE.fullmatch(session_id):
            raise PathNotAllowed("Invalid session id", details={"id": session_id[:64]})
        return session_id

    def folder(self, session_id: str) -> Path:
        """Absolute session folder (validates the id; does not require existence)."""
        return self.root / self.validate_id(session_id)

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "wb") as f:
            f.write(json.dumps(data, indent=1).encode())
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)

    def _read_header(self, session_id: str) -> SessionManifest:
        path = self.folder(session_id) / _HEADER
        if not path.parent.is_dir():
            raise SessionNotFound(details={"id": session_id})
        try:
            return SessionManifest.model_validate_json(path.read_bytes())
        except (OSError, ValueError) as e:
            raise SessionNotFound(
                "Session manifest is missing or corrupt", details={"id": session_id}
            ) from e

    def _flush_header(self, m: SessionManifest) -> None:
        self._write_json(self.folder(m.id) / _HEADER, m.model_dump(mode="json", exclude={"frames"}))
        self._unflushed[m.id] = 0

    def _load(self, session_id: str) -> SessionManifest:
        """Cached header (call under the session lock for read-modify-write)."""
        self.validate_id(session_id)
        m = self._cache.get(session_id)
        if m is None:
            m = self._read_header(session_id)
            self._cache[session_id] = m
        return m

    def _iter_lines(self, session_id: str) -> Iterator[SessionFrame]:
        path = self.folder(session_id) / _FRAMES
        try:
            f = open(path, "rb")  # noqa: SIM115 - generator keeps it open lazily
        except FileNotFoundError:
            return
        with f:
            for raw in f:
                try:
                    yield SessionFrame.model_validate_json(raw)
                except ValueError:
                    continue  # torn / corrupt line

    # ---- create / read -------------------------------------------------------------------
    def _create(self, name: str, config: dict[str, Any], planned_frames: int) -> SessionManifest:
        now = self._clock()
        while True:
            sid = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
            try:
                (self.root / sid).mkdir()
                break
            except FileExistsError:
                continue
        m = SessionManifest(
            id=sid,
            name=name.strip() or sid,
            created=now,
            updated=now,
            config=config,
            planned_frames=planned_frames,
        )
        self._flush_header(m)
        self._cache[sid] = m
        return m

    async def create(
        self, name: str, config: dict[str, Any], planned_frames: int = 0
    ) -> SessionManifest:
        """Create the folder and manifest (status ``configured``). Returns the header."""
        return await asyncio.to_thread(self._create, name, config, planned_frames)

    async def get(self, session_id: str, *, with_frames: bool = False) -> SessionManifest:
        """Manifest header (``frames == []`` unless ``with_frames``). Raises SessionNotFound."""
        self.validate_id(session_id)
        m = self._cache.get(session_id)
        if m is None:
            m = await asyncio.to_thread(self._read_header, session_id)
        out = m.model_copy(deep=True)
        if with_frames:
            out.frames = await self.list_frames(session_id, 0, None)
        return out

    def _list(self) -> list[SessionSummary]:
        out: list[SessionSummary] = []
        for d in self.root.iterdir():
            if not d.is_dir() or not SESSION_ID_RE.fullmatch(d.name):
                continue
            m = self._cache.get(d.name)
            corrupt = False
            if m is None:
                try:
                    m = self._read_header(d.name)
                except SessionNotFound:
                    corrupt = True
            if m is None:
                try:
                    created = datetime.strptime(d.name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
                except ValueError:
                    created = _now()
                out.append(
                    SessionSummary(
                        id=d.name,
                        name=d.name,
                        created=created,
                        updated=created,
                        status=SessionStatus.FAILED,
                        error="Session manifest is missing or corrupt",
                        corrupt=True,
                    )
                )
            else:
                out.append(self.summarize(m, corrupt=corrupt))
        out.sort(key=lambda s: s.id, reverse=True)
        return out

    @staticmethod
    def summarize(m: SessionManifest, *, corrupt: bool = False) -> SessionSummary:
        return SessionSummary(
            **m.model_dump(include=set(SessionSummary.model_fields) - {"video_count", "corrupt"}),
            video_count=len(m.videos),
            corrupt=corrupt,
        )

    async def list(self) -> builtins.list[SessionSummary]:
        """All sessions, newest first; a corrupt folder is reported (status failed, corrupt)."""
        return await asyncio.to_thread(self._list)

    async def delete(self, session_id: str) -> None:
        """Remove the folder. InvalidState while running/paused; SessionNotFound if absent."""
        folder = self.folder(session_id)
        async with self._lock(session_id):
            if not folder.is_dir():
                raise SessionNotFound(details={"id": session_id})
            try:
                m = self._load(session_id)
            except SessionNotFound:
                m = None  # corrupt manifest: allow deletion
            if m is not None and m.status in ACTIVE_STATUSES:
                raise InvalidState(
                    "Stop the session before deleting it", details={"status": str(m.status)}
                )
            await asyncio.to_thread(shutil.rmtree, folder)
            self._cache.pop(session_id, None)
            self._unflushed.pop(session_id, None)
        self._locks.pop(session_id, None)

    # ---- mutation ------------------------------------------------------------------------
    def _append_frame(self, m: SessionManifest, frame: SessionFrame) -> None:
        path = self.folder(m.id) / _FRAMES
        line = frame.model_dump_json().encode() + b"\n"
        with open(path, "ab+") as f:
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    line = b"\n" + line  # repair torn last line
            f.write(line)
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())
        m.frames_captured += 1
        m.updated = _now()
        n = self._unflushed.get(m.id, 0) + 1
        if n >= self._flush_every:
            self._flush_header(m)
        else:
            self._unflushed[m.id] = n

    async def add_frame(self, session_id: str, frame: SessionFrame) -> SessionManifest:
        """Append one frame (O(1) disk write); bumps ``frames_captured``."""
        async with self._lock(session_id):
            m = self._load(session_id)
            await asyncio.to_thread(self._append_frame, m, frame)
            return m.model_copy(deep=True)

    async def update(self, session_id: str, **fields: Any) -> SessionManifest:
        """Set header fields (name, status, config, planned_frames, frames_captured,
        frames_failed, started, finished, error); persists immediately."""
        bad = set(fields) - _UPDATABLE
        if bad:
            raise ValueError(f"cannot update fields: {sorted(bad)}")
        async with self._lock(session_id):
            m = self._load(session_id)
            data = m.model_dump()
            data.update(fields)
            data["updated"] = _now()
            new = SessionManifest.model_validate(data)
            await asyncio.to_thread(self._flush_header, new)
            self._cache[session_id] = new
            return new.model_copy(deep=True)

    async def add_video(self, session_id: str, video: SessionVideo) -> SessionManifest:
        """Record a rendered video; replaces any entry with the same name."""
        async with self._lock(session_id):
            m = self._load(session_id)
            new = m.model_copy(deep=True)
            new.videos = [v for v in new.videos if v.name != video.name] + [video]
            new.updated = _now()
            await asyncio.to_thread(self._flush_header, new)
            self._cache[session_id] = new
            return new.model_copy(deep=True)

    async def remove_video(self, session_id: str, name: str) -> SessionManifest:
        """Drop a video entry (does not delete the file). No-op if absent."""
        async with self._lock(session_id):
            m = self._load(session_id)
            new = m.model_copy(deep=True)
            new.videos = [v for v in new.videos if v.name != name]
            new.updated = _now()
            await asyncio.to_thread(self._flush_header, new)
            self._cache[session_id] = new
            return new.model_copy(deep=True)

    # ---- frames --------------------------------------------------------------------------
    def iter_frames(
        self, session_id: str, offset: int = 0, limit: int | None = None
    ) -> Iterator[SessionFrame]:
        """Lazily yield valid frames ``[offset, offset+limit)`` (sync; use in a thread)."""
        self.validate_id(session_id)
        if not self.folder(session_id).is_dir():
            raise SessionNotFound(details={"id": session_id})
        stop = None if limit is None else offset + limit
        for i, fr in enumerate(self._iter_lines(session_id)):
            if stop is not None and i >= stop:
                return
            if i >= offset:
                yield fr

    async def list_frames(
        self, session_id: str, offset: int = 0, limit: int | None = 50
    ) -> builtins.list[SessionFrame]:
        return await asyncio.to_thread(lambda: list(self.iter_frames(session_id, offset, limit)))

    def _frame_files(
        self, session_id: str, prefer: str, middle_of_bracket: bool
    ) -> builtins.list[Path]:
        folder = self.folder(session_id).resolve()
        frames = list(self._iter_lines(session_id))
        groups: dict[Any, list[SessionFrame]] = {}
        for fr in frames:
            key = ("set", fr.set_index) if (middle_of_bracket and fr.bracket) else ("f", fr.index)
            groups.setdefault(key, []).append(fr)
        out: list[Path] = []
        for group in groups.values():
            group.sort(key=lambda f: (f.bracket.step_index if f.bracket else 0, f.index))
            fr = group[len(group) // 2] if middle_of_bracket else group[0]
            files = sorted(fr.files, key=lambda f: 0 if f.kind == prefer else 1)
            for f in files:
                try:
                    p = safe_join(folder, f.path)
                except PathNotAllowed:
                    continue
                if p.is_file():
                    out.append(p)
                    break
        return out

    async def frame_files(
        self,
        session_id: str,
        *,
        prefer: Literal["jpeg", "raw"] = "jpeg",
        middle_of_bracket: bool = False,
    ) -> builtins.list[Path]:
        """Ordered absolute image paths for rendering: one per frame (or per bracket set,
        choosing the middle step, when ``middle_of_bracket``). Per frame the ``prefer`` kind
        wins, else any other file. Frames whose files are missing/outside the folder are
        skipped."""
        self.validate_id(session_id)
        if not self.folder(session_id).is_dir():
            raise SessionNotFound(details={"id": session_id})
        return await asyncio.to_thread(self._frame_files, session_id, prefer, middle_of_bracket)

    # ---- startup -------------------------------------------------------------------------
    def recover_interrupted(self) -> builtins.list[str]:
        """Mark running/paused sessions ``interrupted`` and recount frames from the log.
        Synchronous: call once at startup (the service factory does). Returns changed ids."""
        changed: list[str] = []
        for d in self.root.iterdir():
            if not d.is_dir() or not SESSION_ID_RE.fullmatch(d.name):
                continue
            try:
                m = self._read_header(d.name)
            except SessionNotFound:
                continue
            if m.status not in ACTIVE_STATUSES:
                continue
            m.status = SessionStatus.INTERRUPTED
            m.finished = m.finished or _now()
            m.updated = _now()
            m.error = m.error or "Interrupted by application restart"
            m.frames_captured = sum(1 for _ in self._iter_lines(d.name))
            self._flush_header(m)
            changed.append(d.name)
        return changed

    async def aclose(self) -> None:
        """Flush headers with pending counter updates."""
        for sid in [s for s, n in self._unflushed.items() if n]:
            async with self._lock(sid):
                m = self._cache.get(sid)
                if m is not None and self.folder(sid).is_dir():
                    await asyncio.to_thread(self._flush_header, m)
