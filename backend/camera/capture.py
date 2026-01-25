"""
Photo Capture Handler

Manages photo capture and file transfer from the camera.

IMPORTANT NOTES:
- Camera needs 1-3 seconds to write file to SD card after capture
- A 2-second delay is added before polling for files
- Live view must be stopped during capture
- RAW+JPEG simultaneous capture is unreliable
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

from backend.camera.exceptions import (
    CameraDisconnectedError,
    CameraStateError,
    CaptureAbortedError,
    CaptureError,
    FileTransferError,
)
from backend.camera.state import CameraState
from backend.config import settings

# Try to import gphoto2
try:
    import gphoto2 as gp
    GPHOTO2_AVAILABLE = True
except ImportError:
    gp = None
    GPHOTO2_AVAILABLE = False


logger = structlog.get_logger(__name__)


class CaptureHandler:
    """
    Handles photo capture and file transfer.

    Usage:
        handler = CaptureHandler(camera, context, lock, controller)
        result = await handler.capture_photo()
        print(f"Saved to: {result.path}")
    """

    def __init__(self, camera, context, lock, controller, output_path: Optional[Path] = None):
        """
        Initialize capture handler.

        Args:
            camera: gphoto2 Camera object
            context: gphoto2 Context object
            lock: threading.Lock for thread-safe access
            controller: CameraController for state management
            output_path: Directory for saving captured files
        """
        self._camera = camera
        self._context = context
        self._lock = lock
        self._controller = controller
        self._output_path = output_path or settings.media.output_path

        # Ensure output directory exists
        self._output_path.mkdir(parents=True, exist_ok=True)

        # Configuration
        self._download_delay = settings.camera.capture_download_delay
        self._capture_timeout = settings.camera.capture_timeout

    async def capture_photo(
        self,
        download: bool = True,
        delete_from_camera: bool = False,
        custom_filename: Optional[str] = None
    ) -> dict:
        """
        Capture a photo and optionally download it.

        Args:
            download: If True, download the file to local storage.
            delete_from_camera: If True, delete from camera after download.
            custom_filename: Optional custom filename (without extension).

        Returns:
            Dictionary with capture result:
            {
                "success": True,
                "camera_path": "/store_00010001/DCIM/100NIKON/DSC_0001.NEF",
                "local_path": "/app/output/20240124_143022_DSC_0001.NEF",
                "filename": "20240124_143022_DSC_0001.NEF",
                "size": 28000000
            }

        Raises:
            CameraStateError: If camera is not ready.
            CaptureError: If capture fails.
            FileTransferError: If download fails.
        """
        # Check state
        if self._controller.state == CameraState.LIVEVIEW:
            logger.info("pausing_liveview_for_capture")
            # Live view will be paused automatically by state machine

        def _do_capture():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                try:
                    # Capture image
                    logger.info("capture_starting")
                    file_path = self._camera.capture(gp.GP_CAPTURE_IMAGE, self._context)

                    return {
                        "folder": file_path.folder,
                        "name": file_path.name,
                    }

                except gp.GPhoto2Error as e:
                    raise CaptureError(f"Capture failed: {e}")

        # Set state to CAPTURING
        original_state = self._controller.state
        self._controller._state = CameraState.CAPTURING

        try:
            # Perform capture
            capture_result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, _do_capture),
                timeout=self._capture_timeout
            )

            logger.info(
                "capture_complete",
                folder=capture_result["folder"],
                name=capture_result["name"]
            )

            result = {
                "success": True,
                "camera_path": f"{capture_result['folder']}/{capture_result['name']}",
                "filename": capture_result["name"],
            }

            # Download if requested
            if download:
                # Wait for camera to write file to card
                logger.info("waiting_for_file_write", delay=self._download_delay)
                await asyncio.sleep(self._download_delay)

                local_path = await self._download_file(
                    capture_result["folder"],
                    capture_result["name"],
                    custom_filename=custom_filename
                )

                result["local_path"] = str(local_path)
                result["size"] = local_path.stat().st_size

                # Delete from camera if requested
                if delete_from_camera:
                    await self._delete_from_camera(
                        capture_result["folder"],
                        capture_result["name"]
                    )

            return result

        except asyncio.TimeoutError:
            raise CaptureError(f"Capture timed out after {self._capture_timeout} seconds")

        finally:
            # Restore original state
            self._controller._state = CameraState.IDLE

    async def _download_file(
        self,
        folder: str,
        filename: str,
        custom_filename: Optional[str] = None
    ) -> Path:
        """
        Download a file from the camera.

        Args:
            folder: Camera folder path
            filename: Camera filename
            custom_filename: Optional custom local filename

        Returns:
            Path to the downloaded file.

        Raises:
            FileTransferError: If download fails.
        """
        def _do_download():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                try:
                    camera_file = self._camera.file_get(
                        folder,
                        filename,
                        gp.GP_FILE_TYPE_NORMAL,
                        self._context
                    )

                    # Generate local filename
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    ext = Path(filename).suffix

                    if custom_filename:
                        local_filename = f"{custom_filename}{ext}"
                    else:
                        local_filename = f"{timestamp}_{filename}"

                    local_path = self._output_path / local_filename

                    # Save file
                    camera_file.save(str(local_path))

                    return local_path

                except gp.GPhoto2Error as e:
                    raise FileTransferError(filename, str(e))

        local_path = await asyncio.get_event_loop().run_in_executor(None, _do_download)

        logger.info(
            "file_downloaded",
            filename=filename,
            local_path=str(local_path),
            size=local_path.stat().st_size
        )

        return local_path

    async def _delete_from_camera(self, folder: str, filename: str) -> None:
        """
        Delete a file from the camera.

        Args:
            folder: Camera folder path
            filename: Camera filename
        """
        def _do_delete():
            with self._lock:
                if not self._camera:
                    return

                try:
                    self._camera.file_delete(folder, filename, self._context)
                except gp.GPhoto2Error:
                    pass  # Ignore delete errors

        await asyncio.get_event_loop().run_in_executor(None, _do_delete)
        logger.info("file_deleted_from_camera", filename=filename)

    async def trigger_capture(self) -> None:
        """
        Trigger capture without waiting for result.

        Useful for burst mode or when you don't need immediate file transfer.
        """
        def _do_trigger():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                try:
                    self._camera.trigger_capture(self._context)
                except gp.GPhoto2Error as e:
                    raise CaptureError(f"Trigger failed: {e}")

        await asyncio.get_event_loop().run_in_executor(None, _do_trigger)
        logger.info("capture_triggered")

    async def list_camera_files(self, folder: str = "/") -> list[dict]:
        """
        List files on the camera.

        Args:
            folder: Camera folder path (default: root)

        Returns:
            List of file information dictionaries.
        """
        def _list_files():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                files = []

                def _walk_folder(path):
                    try:
                        # Get files in this folder
                        for name, _ in self._camera.folder_list_files(path, self._context):
                            info = self._camera.file_get_info(path, name, self._context)
                            files.append({
                                "folder": path,
                                "name": name,
                                "size": info.file.size,
                                "type": info.file.type,
                            })

                        # Recurse into subfolders
                        for name, _ in self._camera.folder_list_folders(path, self._context):
                            subfolder = f"{path}/{name}" if path != "/" else f"/{name}"
                            _walk_folder(subfolder)

                    except gp.GPhoto2Error:
                        pass

                _walk_folder(folder)
                return files

        return await asyncio.get_event_loop().run_in_executor(None, _list_files)

    async def download_all_new_files(
        self,
        delete_after: bool = False
    ) -> list[Path]:
        """
        Download all files from the camera.

        Args:
            delete_after: If True, delete files from camera after download.

        Returns:
            List of paths to downloaded files.
        """
        files = await self.list_camera_files()
        downloaded = []

        for file_info in files:
            try:
                local_path = await self._download_file(
                    file_info["folder"],
                    file_info["name"]
                )
                downloaded.append(local_path)

                if delete_after:
                    await self._delete_from_camera(
                        file_info["folder"],
                        file_info["name"]
                    )

            except FileTransferError as e:
                logger.error("download_failed", error=str(e))

        return downloaded
