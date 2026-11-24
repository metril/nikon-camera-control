"""Capture + download to the local output directory."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.api.schemas.common import EventType
from backend.camera.backend import CameraBackend, CameraFilePath
from backend.camera.backend import EventType as CamEventType
from backend.core.camera_service import (
    CameraService,
    Priority,
    dedupe_slot_copies,
    drain_pending_events,
)
from backend.core.errors import (
    AppError,
    CameraNotConnected,
    CameraTimeout,
    DownloadFailed,
    InvalidState,
    NoTargetError,
)
from backend.core.state import CameraState
from backend.core.storage_root import StorageRoot, as_root
from backend.services.files import FileIndex
from backend.services.storage import download_files

log = logging.getLogger(__name__)

_PREFIX_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_prefix(prefix: str | None) -> str:
    """Safe filename prefix (``[A-Za-z0-9_-]``, max 40 chars) with a trailing ``-``, or ''."""
    cleaned = _PREFIX_BAD.sub("-", prefix or "").strip("_-")[:40].strip("_-")
    return f"{cleaned}-" if cleaned else ""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    local: list[Path]
    camera_files: list[CameraFilePath]


_FIRST_FILE_S = 10.0  # first-file wait beyond the exposure time


class CaptureService:
    """CameraService.capture() already handles state, events and restoring LIVEVIEW, and
    publishes capture_started/capture_complete; this adds the download step only."""

    def __init__(
        self,
        camera: CameraService,
        store: Path | StorageRoot,
        index: FileIndex,
        *,
        keep_card_copy: Callable[[], bool] = lambda: True,
        default_prefix: Callable[[], str | None] = lambda: None,
        downloads_enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        self._downloads_enabled = downloads_enabled
        self._triggered: collections.deque[CameraFilePath] = collections.deque(maxlen=200)
        self._default_prefix = default_prefix
        self._keep_card_copy = keep_card_copy
        self._camera = camera
        self._store = as_root(store)
        self._index = index
        self._bg: set[asyncio.Task[None]] = set()
        camera.stray_handler = self._on_strays

    @property
    def output_dir(self) -> Path:
        return self._store.root()

    async def capture(
        self, *, download: bool, delete_from_camera: bool, filename_prefix: str | None
    ) -> CaptureResult:
        files, local = await self._shoot(
            None,
            download=download,
            owner=None,
            name_prefix=sanitize_prefix(filename_prefix or self._default_prefix()),
            delete_from_camera=delete_from_camera,
        )
        return CaptureResult(local, files)

    async def capture_to(
        self,
        dest_dir: Path,
        *,
        owner: str | None = None,
        name_prefix: str = "",
        delete_from_camera: bool = False,
    ) -> list[Path]:
        """Capture and download into ``dest_dir`` (e.g. a time-lapse session folder), as the
        lease ``owner`` if given. Files: ``<name_prefix>YYYY-mm-dd-HHMMSS-<camera name>``."""
        _, local = await self._shoot(
            dest_dir,
            download=True,
            owner=owner,
            name_prefix=name_prefix,
            delete_from_camera=delete_from_camera,
        )
        return local

    async def _target_is_card(self, owner: str | None) -> bool | None:
        """Whether the camera stores shots on its memory card; None when it can't be read."""
        try:
            w = await self._camera.call(
                lambda b: b.get_config("capturetarget"), priority=Priority.KEEPALIVE, owner=owner
            )
        except AppError:
            return None
        return "ram" not in str(w.value).lower()

    async def _shoot(
        self,
        dest: Path | None,
        *,
        download: bool,
        owner: str | None,
        name_prefix: str,
        delete_from_camera: bool,
    ) -> tuple[list[CameraFilePath], list[Path]]:
        """Capture and, when ``download``, copy every file the shot produced to the host
        location. Camera target and host location are independent: a shot is always downloaded
        to the host location. With the RAM target an unavailable location refuses the shot
        (the photo would be lost); with the card target the shot is taken and stays on the card."""
        self._require_connected()
        card = await self._target_is_card(owner)
        unavailable: NoTargetError | None = None
        root = dest
        if download:
            try:
                base = self._store.root()  # NoTargetError before the shutter fires
                root = dest if dest is not None else base
            except NoTargetError as e:
                if card is not True:  # RAM or unknown: the photo could be lost
                    raise NoTargetError(
                        "The storage location isn't available, so the photo was not taken. "
                        "The camera may save to its internal memory only.",
                        details=e.details,
                    ) from e
                unavailable = e
        files = await self._camera.capture(owner=owner)
        refs = [{"folder": f.folder, "name": f.name} for f in files]
        if not download:
            return files, []
        if unavailable is not None:
            raise NoTargetError(
                "The photo was taken and is still on the camera card, but the storage location "
                "isn't available. Reconnect it and copy the photo from the camera.",
                details={"camera_files": refs},
            ) from unavailable
        if root is None:  # unreachable: download implies a resolved destination
            raise NoTargetError()
        local = await self._download(
            files,
            root,
            owner=owner,
            name_prefix=name_prefix,
            delete_from_camera=card is True and (delete_from_camera or not self._keep_card_copy()),
        )
        return files, local

    def _on_strays(self, files: list[CameraFilePath]) -> None:
        """Files the camera announced outside a capture (a late NEF): fetch them in the
        background. With no storage location they stay on the card (and in ``stray_files``)."""
        task = asyncio.get_running_loop().create_task(self._download_strays(files))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _download_strays(self, files: list[CameraFilePath]) -> None:
        files = [f for f in files if f not in self._triggered]
        if not files or not self._downloads_enabled():
            return  # trigger-only shots and downloads-off: files stay on the card
        try:
            root = self._store.root()
        except NoTargetError:
            log.warning("late camera files left on the card: no storage location")
            return
        try:
            files = await self._camera.call(
                lambda b: dedupe_slot_copies(b, files), priority=Priority.KEEPALIVE
            )
            await self._download(
                files,
                root,
                owner=None,
                name_prefix="",
                delete_from_camera=False,  # a stray is never removed from the card
            )
        except AppError as e:
            log.warning("late camera files not downloaded: %s", e.message)
            return
        for f in files:
            with contextlib.suppress(ValueError):
                self._camera.stray_files.remove(f)
        self._camera.bus.publish(
            EventType.CAPTURE_COMPLETE,
            {"files": [{"folder": f.folder, "name": f.name} for f in files]},
        )

    def _require_connected(self) -> None:
        if not self._camera.status().connected:
            raise CameraNotConnected()

    async def trigger(self) -> None:
        """Fire the shutter only. Refused with the RAM target: the photo would be lost."""
        self._require_connected()
        if await self._target_is_card(None) is False:
            raise InvalidState(
                "The camera saves to its internal memory, so the photo would be lost. "
                "Set the camera to save to the memory card first."
            )
        await self._camera.refuse_bulb_shutter()

        wait_s = self._camera.capture_timeout_s
        quiet = self._camera.quiet_window_s
        first_s = min(wait_s, _FIRST_FILE_S + self._camera.exposure_hint_s())
        loop = asyncio.get_running_loop()

        def _fire(b: CameraBackend) -> list[CameraFilePath]:
            # Events already pending (a late NEF, a body-shutter shot) are not this shot's.
            late: list[CameraFilePath] = []
            drain_pending_events(b, keep=late)
            if late:
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(self._on_strays, late)
            b.trigger()
            seen: list[CameraFilePath] = []
            # The shot's own file events are never ours: wait for the first (exposure + write),
            # then until a quiet window passes with no further file. Chatter neither ends nor
            # counts.
            deadline = time.monotonic() + first_s
            last: float | None = None
            while True:
                now = time.monotonic()
                end = deadline if last is None else min(deadline, last + quiet)
                if end - now <= 0:
                    break
                ev = b.wait_for_event(min(end - now, 0.5))
                if ev.type == CamEventType.FILE_ADDED and ev.file is not None:
                    if last is None:  # first file: later ones may follow for the full window
                        deadline = time.monotonic() + wait_s
                    last = time.monotonic()
                    if ev.file not in seen:
                        seen.append(ev.file)
                elif ev.type == CamEventType.CAPTURE_COMPLETE and last is None:
                    break
            return seen

        prior = await self._camera.transition(CameraState.CAPTURING)
        try:
            files = await self._camera.call(
                _fire, priority=Priority.CAPTURE, timeout=wait_s + first_s + quiet + 5.0
            )
        finally:
            if self._camera.state == CameraState.CAPTURING:
                with contextlib.suppress(AppError):
                    await self._camera.transition(prior)
        if not files:
            raise CameraTimeout("The camera didn't take a photo. Check focus and the card.")
        self._triggered.extend(f for f in files if f not in self._triggered)

    async def _download(
        self,
        files: list[CameraFilePath],
        dest: Path,
        *,
        owner: str | None,
        name_prefix: str,
        delete_from_camera: bool,
    ) -> list[Path]:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S-")
        saved = 0

        def stored(path: Path) -> None:
            nonlocal saved
            saved += 1
            self._store.stored(path)

        try:
            return await download_files(
                self._camera,
                files,
                dest,
                owner=owner,
                delete_from_camera=delete_from_camera,
                name_prefix=f"{name_prefix}{stamp}",
                on_stored=stored,
            )
        except (AppError, OSError) as e:
            if isinstance(e, NoTargetError | DownloadFailed):
                raise
            raise DownloadFailed(
                details={
                    "cause": str(e),
                    "cause_code": str(getattr(e, "code", type(e).__name__)),
                    "camera_files": [{"folder": f.folder, "name": f.name} for f in files[saved:]],
                },
                recoverable=getattr(e, "recoverable", True),
            ) from e
        finally:
            self._index.invalidate()
