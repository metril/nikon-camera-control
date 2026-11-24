"""Capture + download to the local output directory."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.camera.backend import CameraFilePath
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import AppError, CameraNotConnected, DownloadFailed, NoTargetError
from backend.core.storage_root import StorageRoot, as_root
from backend.services.files import FileIndex
from backend.services.storage import download_files

_PREFIX_BAD = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_prefix(prefix: str | None) -> str:
    """Safe filename prefix (``[A-Za-z0-9_-]``, max 40 chars) with a trailing ``_``, or ''."""
    cleaned = _PREFIX_BAD.sub("_", prefix or "").strip("_")[:40]
    return f"{cleaned}_" if cleaned else ""


@dataclass(frozen=True, slots=True)
class CaptureResult:
    local: list[Path]
    camera_files: list[CameraFilePath]


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
    ) -> None:
        self._keep_card_copy = keep_card_copy
        self._camera = camera
        self._store = as_root(store)
        self._index = index

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
            name_prefix=sanitize_prefix(filename_prefix),
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
        lease ``owner`` if given. Files are named ``<name_prefix>YYYYmmdd_HHMMSS_<camera name>``."""
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

    def _require_connected(self) -> None:
        if not self._camera.status().connected:
            raise CameraNotConnected()

    async def trigger(self) -> None:
        await self._camera.call(lambda b: b.trigger(), priority=Priority.CAPTURE)

    async def _download(
        self,
        files: list[CameraFilePath],
        dest: Path,
        *,
        owner: str | None,
        name_prefix: str,
        delete_from_camera: bool,
    ) -> list[Path]:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
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
