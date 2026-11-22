"""Capture + download to the local output directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backend.camera.backend import CameraFilePath
from backend.core.camera_service import CameraService, Priority
from backend.core.errors import CameraNotConnected
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

    def __init__(self, camera: CameraService, output_dir: Path, index: FileIndex) -> None:
        self._camera = camera
        self._output = output_dir
        self.output_dir = output_dir
        self._index = index

    async def capture(
        self, *, download: bool, delete_from_camera: bool, filename_prefix: str | None
    ) -> CaptureResult:
        self._require_connected()
        files = await self._camera.capture()
        if not download:
            return CaptureResult([], files)
        local = await self._download(
            files,
            self._output,
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
        self._require_connected()
        files = await self._camera.capture(owner=owner)
        return await self._download(
            files,
            dest_dir,
            owner=owner,
            name_prefix=name_prefix,
            delete_from_camera=delete_from_camera,
        )

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
        try:
            return await download_files(
                self._camera,
                files,
                dest,
                owner=owner,
                delete_from_camera=delete_from_camera,
                name_prefix=f"{name_prefix}{stamp}",
            )
        finally:
            self._index.invalidate()
