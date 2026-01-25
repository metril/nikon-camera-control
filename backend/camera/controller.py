"""
Camera Controller

Core class for managing Nikon D500 camera connection and operations.
Implements thread-safe access with state machine and keep-alive mechanism.

CRITICAL NOTES:
- gphoto2 is a BLOCKING library - all camera calls use threading.Lock
- D500 times out after 60 seconds without commands - keep-alive is essential
- Only ONE operation can run at a time (PTP protocol limitation)
"""

import asyncio
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Optional

import structlog

from backend.camera.exceptions import (
    CameraBusyError,
    CameraConnectionError,
    CameraDisconnectedError,
    CameraNotFoundError,
    CameraStateError,
    CameraTimeoutError,
)
from backend.camera.state import CameraState, can_transition, STATE_DESCRIPTIONS
from backend.config import settings

# Try to import gphoto2, handle gracefully if not available
try:
    import gphoto2 as gp
    GPHOTO2_AVAILABLE = True
except ImportError:
    gp = None
    GPHOTO2_AVAILABLE = False


logger = structlog.get_logger(__name__)


class CameraController:
    """
    Thread-safe camera controller with state machine and keep-alive.

    Usage:
        controller = CameraController()
        await controller.connect()
        status = await controller.get_status()
        await controller.disconnect()
    """

    def __init__(self):
        # Camera objects (set when connected)
        self._camera: Optional[Any] = None  # gp.Camera
        self._context: Optional[Any] = None  # gp.Context

        # Thread safety
        self._lock = threading.RLock()  # Reentrant lock for nested calls
        self._operation_lock = threading.Lock()  # For exclusive operations

        # State machine
        self._state = CameraState.DISCONNECTED
        self._state_changed_at = datetime.now()
        self._last_activity = datetime.now()

        # Keep-alive
        self._keepalive_thread: Optional[threading.Thread] = None
        self._keepalive_stop_event = threading.Event()

        # Event callbacks
        self._on_disconnect_callbacks: list[Callable[[], None]] = []
        self._on_state_change_callbacks: list[Callable[[CameraState, CameraState], None]] = []

        # Camera info (cached after connection)
        self._camera_model: Optional[str] = None
        self._camera_serial: Optional[str] = None

    @property
    def state(self) -> CameraState:
        """Current camera state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if camera is connected."""
        return self._state not in (CameraState.DISCONNECTED, CameraState.ERROR)

    @property
    def camera_model(self) -> Optional[str]:
        """Camera model name (e.g., 'Nikon D500')."""
        return self._camera_model

    def _set_state(self, new_state: CameraState) -> None:
        """
        Transition to a new state with validation.

        Raises:
            CameraStateError: If transition is not valid.
        """
        old_state = self._state

        if not can_transition(old_state, new_state):
            raise CameraStateError(
                operation="state transition",
                current_state=old_state.name,
                required_states=[s.name for s in self._get_allowed_next_states()]
            )

        self._state = new_state
        self._state_changed_at = datetime.now()

        logger.info(
            "camera_state_changed",
            from_state=old_state.name,
            to_state=new_state.name
        )

        # Notify callbacks
        for callback in self._on_state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                logger.error("state_change_callback_error", error=str(e))

    def _get_allowed_next_states(self) -> list[CameraState]:
        """Get states we can transition to from current state."""
        from backend.camera.state import get_allowed_transitions
        return list(get_allowed_transitions(self._state))

    def _update_activity(self) -> None:
        """Mark that camera activity occurred (for keep-alive tracking)."""
        self._last_activity = datetime.now()

    @contextmanager
    def _camera_operation(self, operation_name: str):
        """
        Context manager for thread-safe camera operations.

        Acquires lock, validates connection, updates activity timestamp.

        Usage:
            with self._camera_operation("take_photo"):
                # camera operations here
                pass
        """
        if not self._operation_lock.acquire(timeout=5.0):
            raise CameraBusyError(operation_name)

        try:
            with self._lock:
                if not self.is_connected:
                    raise CameraDisconnectedError()
                self._update_activity()
                yield self._camera, self._context
        finally:
            self._operation_lock.release()

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self) -> bool:
        """
        Connect to the camera.

        Returns:
            True if connection successful.

        Raises:
            CameraNotFoundError: If no camera detected.
            CameraConnectionError: If connection fails.
        """
        if not GPHOTO2_AVAILABLE:
            raise CameraConnectionError(
                "gphoto2 library not available. Install with: pip install gphoto2"
            )

        def _do_connect() -> bool:
            with self._lock:
                if self.is_connected:
                    logger.info("camera_already_connected")
                    return True

                try:
                    logger.info("camera_connecting")

                    # Initialize context and camera
                    self._context = gp.Context()
                    self._camera = gp.Camera()

                    # Attempt to initialize (this detects the camera)
                    self._camera.init(self._context)

                    # Get camera info
                    abilities = self._camera.get_abilities()
                    self._camera_model = abilities.model

                    try:
                        summary = self._camera.get_summary(self._context)
                        # Parse serial from summary if available
                        for line in str(summary).split('\n'):
                            if 'Serial' in line:
                                self._camera_serial = line.split(':')[-1].strip()
                                break
                    except Exception:
                        pass

                    # Transition to IDLE state
                    self._state = CameraState.IDLE
                    self._state_changed_at = datetime.now()
                    self._update_activity()

                    logger.info(
                        "camera_connected",
                        model=self._camera_model,
                        serial=self._camera_serial
                    )

                    return True

                except gp.GPhoto2Error as e:
                    self._cleanup_connection()

                    error_code = e.code if hasattr(e, 'code') else -1

                    if error_code == gp.GP_ERROR_MODEL_NOT_FOUND:
                        raise CameraNotFoundError()
                    elif error_code == gp.GP_ERROR_IO:
                        raise CameraConnectionError(
                            "USB I/O error. Check cable and try reconnecting."
                        )
                    else:
                        raise CameraConnectionError(f"Connection failed: {e}")

        # Run blocking operation in thread pool
        result = await asyncio.get_event_loop().run_in_executor(None, _do_connect)

        # Start keep-alive after successful connection
        if result and settings.camera.keepalive_enabled:
            self._start_keepalive()

        return result

    async def disconnect(self) -> None:
        """Disconnect from the camera gracefully."""
        def _do_disconnect():
            with self._lock:
                self._stop_keepalive()
                self._cleanup_connection()
                self._state = CameraState.DISCONNECTED
                self._state_changed_at = datetime.now()
                logger.info("camera_disconnected")

        await asyncio.get_event_loop().run_in_executor(None, _do_disconnect)

        # Notify disconnect callbacks
        for callback in self._on_disconnect_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error("disconnect_callback_error", error=str(e))

    def _cleanup_connection(self) -> None:
        """Clean up camera resources."""
        if self._camera:
            try:
                self._camera.exit(self._context)
            except Exception:
                pass
            self._camera = None
        self._context = None
        self._camera_model = None
        self._camera_serial = None

    # =========================================================================
    # Keep-Alive Mechanism
    # =========================================================================

    def _start_keepalive(self) -> None:
        """Start the keep-alive background thread."""
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return

        self._keepalive_stop_event.clear()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_worker,
            daemon=True,
            name="camera-keepalive"
        )
        self._keepalive_thread.start()
        logger.info("keepalive_started", interval=settings.camera.keepalive_interval)

    def _stop_keepalive(self) -> None:
        """Stop the keep-alive background thread."""
        if self._keepalive_thread:
            self._keepalive_stop_event.set()
            self._keepalive_thread.join(timeout=5.0)
            self._keepalive_thread = None
            logger.info("keepalive_stopped")

    def _keepalive_worker(self) -> None:
        """
        Background thread that sends periodic pings to prevent camera timeout.

        The Nikon D500 times out after 60 seconds without PTP commands.
        This worker sends a lightweight command every 30 seconds.
        """
        interval = settings.camera.keepalive_interval

        while not self._keepalive_stop_event.wait(timeout=interval):
            if not self.is_connected:
                break

            # Check if we need to send a ping (no activity recently)
            seconds_since_activity = (datetime.now() - self._last_activity).total_seconds()

            if seconds_since_activity >= interval * 0.8:  # 80% of interval
                try:
                    self._send_keepalive_ping()
                except Exception as e:
                    logger.warning("keepalive_ping_failed", error=str(e))
                    # Don't break - let the main code handle disconnection

    def _send_keepalive_ping(self) -> None:
        """
        Send a lightweight command to keep the connection alive.

        Uses get_config() as a lightweight ping that doesn't change camera state.
        """
        with self._lock:
            if not self.is_connected or not self._camera:
                return

            try:
                # get_summary() is a lightweight read-only operation
                self._camera.get_summary(self._context)
                self._update_activity()
                logger.debug("keepalive_ping_sent")
            except Exception as e:
                logger.warning("keepalive_ping_error", error=str(e))
                raise

    # =========================================================================
    # Status and Information
    # =========================================================================

    async def get_status(self) -> dict:
        """
        Get current camera status.

        Returns:
            Dictionary with connection status, state, model info.
        """
        return {
            "connected": self.is_connected,
            "state": self._state.name,
            "state_description": STATE_DESCRIPTIONS.get(self._state, "Unknown"),
            "model": self._camera_model,
            "serial": self._camera_serial,
            "last_activity": self._last_activity.isoformat() if self._last_activity else None,
            "keepalive_enabled": settings.camera.keepalive_enabled,
        }

    async def get_summary(self) -> Optional[str]:
        """Get camera summary/info text."""
        if not self.is_connected:
            return None

        def _get_summary():
            with self._camera_operation("get_summary"):
                summary = self._camera.get_summary(self._context)
                return str(summary)

        return await asyncio.get_event_loop().run_in_executor(None, _get_summary)

    # =========================================================================
    # Event Callbacks
    # =========================================================================

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        """Register a callback for disconnect events."""
        self._on_disconnect_callbacks.append(callback)

    def on_state_change(self, callback: Callable[[CameraState, CameraState], None]) -> None:
        """Register a callback for state change events."""
        self._on_state_change_callbacks.append(callback)

    # =========================================================================
    # Reconnection with Retry
    # =========================================================================

    async def connect_with_retry(
        self,
        max_retries: Optional[int] = None,
        retry_interval: Optional[float] = None
    ) -> bool:
        """
        Attempt to connect with automatic retries.

        Args:
            max_retries: Maximum number of retry attempts (default from config).
            retry_interval: Seconds between retries (default from config).

        Returns:
            True if connection successful.

        Raises:
            CameraConnectionError: After all retries exhausted.
        """
        retries = max_retries or settings.camera.reconnect_max_retries
        interval = retry_interval or settings.camera.reconnect_interval

        last_error = None

        for attempt in range(1, retries + 1):
            try:
                logger.info("connection_attempt", attempt=attempt, max_retries=retries)
                return await self.connect()

            except CameraNotFoundError as e:
                last_error = e
                logger.warning(
                    "camera_not_found",
                    attempt=attempt,
                    retry_in=interval
                )

            except CameraConnectionError as e:
                last_error = e
                logger.warning(
                    "connection_failed",
                    attempt=attempt,
                    error=str(e),
                    retry_in=interval
                )

            if attempt < retries:
                await asyncio.sleep(interval)
                # Exponential backoff
                interval = min(interval * 1.5, 30.0)

        raise CameraConnectionError(
            f"Failed to connect after {retries} attempts. Last error: {last_error}"
        )
