"""
Live View Handler

Manages live view streaming from the camera.
Provides frame capture at 5-10 FPS via binary WebSocket.

IMPORTANT NOTES:
- D500 times out after 60 seconds without commands
- Keep-alive is handled by the CameraController
- Frames are JPEG format, typically 800KB-1.2MB each
- Maximum realistic FPS is 5-10 due to USB 2.0 bandwidth
"""

import asyncio
import threading
import time
from datetime import datetime
from typing import AsyncGenerator, Optional

import structlog

from backend.camera.exceptions import (
    CameraDisconnectedError,
    CameraStateError,
    LiveViewError,
    LiveViewTimeoutError,
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


class LiveViewHandler:
    """
    Handles live view streaming from the camera.

    Usage:
        handler = LiveViewHandler(camera, context, lock)
        await handler.start()
        async for frame in handler.stream_frames():
            # Send frame to WebSocket client
            pass
        await handler.stop()
    """

    def __init__(self, camera, context, lock, controller):
        """
        Initialize live view handler.

        Args:
            camera: gphoto2 Camera object
            context: gphoto2 Context object
            lock: threading.Lock for thread-safe access
            controller: CameraController for state management
        """
        self._camera = camera
        self._context = context
        self._lock = lock
        self._controller = controller

        # State
        self._active = False
        self._stop_event = threading.Event()

        # Performance tracking
        self._frames_captured = 0
        self._last_frame_time: Optional[datetime] = None
        self._fps_actual = 0.0

        # Configuration
        self._target_fps = settings.camera.liveview_target_fps
        self._frame_timeout = settings.camera.liveview_frame_timeout

    @property
    def is_active(self) -> bool:
        """Check if live view is currently streaming."""
        return self._active

    @property
    def fps(self) -> float:
        """Current actual frames per second."""
        return self._fps_actual

    @property
    def frames_captured(self) -> int:
        """Total frames captured in current session."""
        return self._frames_captured

    async def start(self) -> bool:
        """
        Start live view mode.

        Enables the camera's viewfinder/live view mode.

        Returns:
            True if live view started successfully.

        Raises:
            CameraStateError: If camera is not in IDLE state.
            LiveViewError: If live view could not be started.
        """
        if self._active:
            logger.info("live_view_already_active")
            return True

        def _start_liveview():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                try:
                    # Get config
                    config = self._camera.get_config(self._context)

                    # Try to enable viewfinder
                    try:
                        viewfinder = config.get_child_by_name('viewfinder')
                        viewfinder.set_value(1)
                        self._camera.set_config(config, self._context)
                    except gp.GPhoto2Error:
                        # Some cameras don't have this setting
                        pass

                    # Try a preview capture to verify it works
                    camera_file = self._camera.capture_preview(self._context)
                    # Discard the test frame
                    del camera_file

                    return True

                except gp.GPhoto2Error as e:
                    raise LiveViewError(f"Failed to start live view: {e}")

        result = await asyncio.get_event_loop().run_in_executor(None, _start_liveview)

        if result:
            self._active = True
            self._stop_event.clear()
            self._frames_captured = 0
            self._controller._set_state(CameraState.LIVEVIEW)
            logger.info("live_view_started", target_fps=self._target_fps)

        return result

    async def stop(self) -> None:
        """
        Stop live view mode.

        Disables the camera's viewfinder and returns to IDLE state.
        """
        if not self._active:
            return

        self._stop_event.set()
        self._active = False

        def _stop_liveview():
            with self._lock:
                if not self._camera:
                    return

                try:
                    config = self._camera.get_config(self._context)
                    try:
                        viewfinder = config.get_child_by_name('viewfinder')
                        viewfinder.set_value(0)
                        self._camera.set_config(config, self._context)
                    except gp.GPhoto2Error:
                        pass
                except Exception:
                    pass

        await asyncio.get_event_loop().run_in_executor(None, _stop_liveview)

        self._controller._set_state(CameraState.IDLE)
        logger.info(
            "live_view_stopped",
            frames_captured=self._frames_captured,
            avg_fps=self._fps_actual
        )

    async def capture_frame(self) -> Optional[bytes]:
        """
        Capture a single live view frame.

        Returns:
            JPEG image data as bytes, or None if capture failed.
        """
        if not self._active:
            return None

        def _capture_frame():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                try:
                    camera_file = self._camera.capture_preview(self._context)
                    file_data = camera_file.get_data_and_size()
                    return bytes(file_data)
                except gp.GPhoto2Error as e:
                    if "timeout" in str(e).lower():
                        raise LiveViewTimeoutError()
                    raise LiveViewError(f"Frame capture failed: {e}")

        try:
            frame = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, _capture_frame),
                timeout=self._frame_timeout
            )
            return frame
        except asyncio.TimeoutError:
            raise LiveViewTimeoutError()

    async def stream_frames(self) -> AsyncGenerator[bytes, None]:
        """
        Generator that yields live view frames for streaming.

        Yields JPEG frames at approximately the target FPS.
        Handles frame rate limiting and error recovery.

        Yields:
            JPEG image data as bytes.
        """
        if not self._active:
            raise LiveViewError("Live view not started")

        frame_interval = 1.0 / self._target_fps
        fps_window: list[float] = []  # For calculating rolling average FPS

        while self._active and not self._stop_event.is_set():
            frame_start = time.time()

            try:
                frame = await self.capture_frame()

                if frame:
                    self._frames_captured += 1
                    self._last_frame_time = datetime.now()

                    # Calculate FPS
                    fps_window.append(time.time())
                    # Keep last 10 frame times
                    fps_window = fps_window[-10:]
                    if len(fps_window) >= 2:
                        self._fps_actual = (len(fps_window) - 1) / (fps_window[-1] - fps_window[0])

                    yield frame

            except LiveViewTimeoutError:
                logger.warning("live_view_frame_timeout")
                # Brief pause before retry
                await asyncio.sleep(0.1)
                continue

            except LiveViewError as e:
                logger.error("live_view_error", error=str(e))
                # Longer pause for other errors
                await asyncio.sleep(0.5)
                continue

            except CameraDisconnectedError:
                logger.error("camera_disconnected_during_liveview")
                self._active = False
                break

            # Frame rate limiting
            elapsed = time.time() - frame_start
            if elapsed < frame_interval:
                await asyncio.sleep(frame_interval - elapsed)

    async def get_status(self) -> dict:
        """Get current live view status."""
        return {
            "active": self._active,
            "frames_captured": self._frames_captured,
            "fps_actual": round(self._fps_actual, 1),
            "fps_target": self._target_fps,
            "last_frame_time": self._last_frame_time.isoformat() if self._last_frame_time else None,
        }
