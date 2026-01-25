"""
Time-lapse capture and video generation handler.
"""
import asyncio
import threading
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List
from enum import Enum

from ..config import settings


class TimelapseState(Enum):
    """Time-lapse session states."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    GENERATING = "generating"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TimelapseHandler:
    """
    Handles time-lapse capture sessions and video generation.

    Known limitation: Software intervalometer has ±500ms jitter per frame.
    For precise intervals, use camera's built-in intervalometer if available.
    """

    def __init__(self, capture_callback: Callable, event_callback: Optional[Callable] = None):
        """
        Initialize time-lapse handler.

        Args:
            capture_callback: Async function to call for each capture
            event_callback: Optional callback for progress events
        """
        self._capture_callback = capture_callback
        self._event_callback = event_callback

        self._state = TimelapseState.IDLE
        self._lock = threading.Lock()

        # Session configuration
        self._interval_seconds: float = 5.0
        self._total_frames: int = 0
        self._duration_seconds: int = 0

        # Session state
        self._frames_captured: int = 0
        self._captured_files: List[str] = []
        self._start_time: Optional[datetime] = None
        self._session_folder: Optional[Path] = None

        # Control
        self._stop_event = threading.Event()
        self._capture_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> TimelapseState:
        """Get current time-lapse state."""
        return self._state

    @property
    def progress(self) -> dict:
        """Get current progress information."""
        with self._lock:
            elapsed = 0
            if self._start_time:
                elapsed = (datetime.now() - self._start_time).total_seconds()

            remaining_frames = max(0, self._total_frames - self._frames_captured)
            estimated_remaining = remaining_frames * self._interval_seconds

            return {
                "state": self._state.value,
                "frames_captured": self._frames_captured,
                "total_frames": self._total_frames,
                "interval_seconds": self._interval_seconds,
                "elapsed_seconds": int(elapsed),
                "estimated_remaining_seconds": int(estimated_remaining),
                "captured_files": self._captured_files.copy(),
                "session_folder": str(self._session_folder) if self._session_folder else None,
            }

    def configure(
        self,
        interval_seconds: float,
        total_frames: Optional[int] = None,
        duration_seconds: Optional[int] = None
    ) -> dict:
        """
        Configure time-lapse session parameters.

        Args:
            interval_seconds: Seconds between captures (minimum 2s for RAW, 1s for JPEG)
            total_frames: Number of frames to capture (use this OR duration_seconds)
            duration_seconds: Total duration in seconds (use this OR total_frames)

        Returns:
            Configuration summary with estimated values
        """
        if self._state == TimelapseState.RUNNING:
            raise RuntimeError("Cannot configure while time-lapse is running")

        # Validate interval
        if interval_seconds < 1.0:
            raise ValueError("Minimum interval is 1 second (2 seconds recommended for RAW)")

        self._interval_seconds = interval_seconds

        # Calculate frames from duration or use provided count
        if duration_seconds is not None:
            self._duration_seconds = duration_seconds
            self._total_frames = int(duration_seconds / interval_seconds)
        elif total_frames is not None:
            self._total_frames = total_frames
            self._duration_seconds = int(total_frames * interval_seconds)
        else:
            raise ValueError("Must specify either total_frames or duration_seconds")

        # Estimate disk space (rough estimate: 20MB per RAW, 5MB per JPEG)
        estimated_size_mb = self._total_frames * 20  # Assume RAW

        return {
            "interval_seconds": self._interval_seconds,
            "total_frames": self._total_frames,
            "duration_seconds": self._duration_seconds,
            "estimated_size_mb": estimated_size_mb,
            "estimated_video_duration_30fps": self._total_frames / 30,
            "estimated_video_duration_24fps": self._total_frames / 24,
        }

    async def start(self) -> bool:
        """
        Start time-lapse capture session.

        Returns:
            True if started successfully
        """
        if self._state == TimelapseState.RUNNING:
            return False

        if self._total_frames == 0:
            raise RuntimeError("Time-lapse not configured. Call configure() first.")

        # Create session folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._session_folder = Path(settings.media.output_path) / f"timelapse_{timestamp}"
        self._session_folder.mkdir(parents=True, exist_ok=True)

        # Reset state
        self._frames_captured = 0
        self._captured_files = []
        self._start_time = datetime.now()
        self._stop_event.clear()
        self._state = TimelapseState.RUNNING

        # Start capture loop
        self._capture_task = asyncio.create_task(self._capture_loop())

        await self._emit_event("timelapse_started", self.progress)
        return True

    async def stop(self) -> dict:
        """
        Stop time-lapse capture session.

        Returns:
            Final progress information
        """
        if self._state != TimelapseState.RUNNING:
            return self.progress

        self._stop_event.set()
        self._state = TimelapseState.CANCELLED

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass

        await self._emit_event("timelapse_stopped", self.progress)
        return self.progress

    async def pause(self) -> bool:
        """Pause time-lapse capture."""
        if self._state != TimelapseState.RUNNING:
            return False

        self._state = TimelapseState.PAUSED
        await self._emit_event("timelapse_paused", self.progress)
        return True

    async def resume(self) -> bool:
        """Resume paused time-lapse capture."""
        if self._state != TimelapseState.PAUSED:
            return False

        self._state = TimelapseState.RUNNING
        await self._emit_event("timelapse_resumed", self.progress)
        return True

    async def _capture_loop(self):
        """Main capture loop for time-lapse."""
        try:
            while self._frames_captured < self._total_frames:
                if self._stop_event.is_set():
                    break

                # Wait while paused
                while self._state == TimelapseState.PAUSED:
                    await asyncio.sleep(0.1)
                    if self._stop_event.is_set():
                        return

                # Capture frame
                try:
                    capture_start = datetime.now()
                    result = await self._capture_callback()

                    if result and result.get("filename"):
                        filename = result["filename"]
                        with self._lock:
                            self._frames_captured += 1
                            self._captured_files.append(filename)

                        await self._emit_event("timelapse_frame", {
                            "frame_number": self._frames_captured,
                            "filename": filename,
                            **self.progress
                        })

                    # Calculate sleep time accounting for capture duration
                    capture_duration = (datetime.now() - capture_start).total_seconds()
                    sleep_time = max(0, self._interval_seconds - capture_duration)

                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

                except Exception as e:
                    await self._emit_event("timelapse_error", {
                        "error": str(e),
                        "frame_number": self._frames_captured + 1,
                        **self.progress
                    })
                    # Continue with next frame despite error
                    await asyncio.sleep(self._interval_seconds)

            # Completed successfully
            if not self._stop_event.is_set():
                self._state = TimelapseState.COMPLETED
                await self._emit_event("timelapse_completed", self.progress)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._state = TimelapseState.ERROR
            await self._emit_event("timelapse_error", {
                "error": str(e),
                **self.progress
            })

    async def generate_video(
        self,
        output_filename: Optional[str] = None,
        fps: int = 24,
        codec: str = "h264",
        quality: str = "high"
    ) -> Optional[str]:
        """
        Generate video from captured time-lapse frames.

        Args:
            output_filename: Output video filename (default: auto-generated)
            fps: Output video framerate (default: 24)
            codec: Video codec - h264, h265, or prores (default: h264)
            quality: Quality preset - low, medium, high (default: high)

        Returns:
            Path to generated video file, or None if failed
        """
        if not self._captured_files:
            raise RuntimeError("No frames captured for video generation")

        if not self._session_folder or not self._session_folder.exists():
            raise RuntimeError("Session folder not found")

        # Check for FFmpeg
        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg not found. Install FFmpeg to generate videos.")

        self._state = TimelapseState.GENERATING
        await self._emit_event("timelapse_generating", {"fps": fps, "codec": codec})

        # Determine output filename
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "mov" if codec == "prores" else "mp4"
            output_filename = f"timelapse_{timestamp}.{ext}"

        output_path = Path(settings.media.output_path) / output_filename

        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(fps, codec, quality, output_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown FFmpeg error"
                raise RuntimeError(f"FFmpeg failed: {error_msg}")

            self._state = TimelapseState.COMPLETED
            await self._emit_event("timelapse_video_ready", {
                "video_path": str(output_path),
                "fps": fps,
                "codec": codec
            })

            return str(output_path)

        except Exception as e:
            self._state = TimelapseState.ERROR
            await self._emit_event("timelapse_error", {"error": str(e)})
            raise

    def _build_ffmpeg_command(
        self,
        fps: int,
        codec: str,
        quality: str,
        output_path: Path
    ) -> List[str]:
        """Build FFmpeg command for video generation."""
        # Create file list for FFmpeg
        file_list_path = self._session_folder / "filelist.txt"
        with open(file_list_path, "w") as f:
            for filename in self._captured_files:
                filepath = Path(settings.media.output_path) / filename
                if filepath.exists():
                    f.write(f"file '{filepath}'\n")
                    f.write(f"duration {1/fps}\n")

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
        ]

        # Codec settings
        quality_map = {
            "low": {"h264": "28", "h265": "30", "prores": "3"},
            "medium": {"h264": "23", "h265": "25", "prores": "2"},
            "high": {"h264": "18", "h265": "20", "prores": "1"},
        }

        if codec == "h264":
            crf = quality_map[quality]["h264"]
            cmd.extend([
                "-c:v", "libx264",
                "-crf", crf,
                "-preset", "slow",
                "-pix_fmt", "yuv420p",
            ])
        elif codec == "h265":
            crf = quality_map[quality]["h265"]
            cmd.extend([
                "-c:v", "libx265",
                "-crf", crf,
                "-preset", "slow",
                "-pix_fmt", "yuv420p",
            ])
        elif codec == "prores":
            profile = quality_map[quality]["prores"]
            cmd.extend([
                "-c:v", "prores_ks",
                "-profile:v", profile,
                "-pix_fmt", "yuv422p10le",
            ])

        cmd.extend([
            "-r", str(fps),
            str(output_path)
        ])

        return cmd

    async def _emit_event(self, event_type: str, data: dict):
        """Emit event via callback."""
        if self._event_callback:
            try:
                await self._event_callback(event_type, data)
            except Exception as e:
                pass  # Don't let event errors affect time-lapse

    def get_disk_space_estimate(self, total_frames: int, format_type: str = "raw") -> dict:
        """
        Estimate disk space required for time-lapse.

        Args:
            total_frames: Number of frames to capture
            format_type: Image format - 'raw' or 'jpeg'

        Returns:
            Disk space estimates
        """
        # Estimates for D500
        size_per_frame_mb = {
            "raw": 45,  # NEF uncompressed
            "raw_compressed": 25,  # NEF lossless compressed
            "jpeg_fine": 12,
            "jpeg_normal": 6,
            "jpeg_basic": 3,
        }

        frame_size = size_per_frame_mb.get(format_type, 25)
        total_mb = total_frames * frame_size

        return {
            "frame_size_mb": frame_size,
            "total_mb": total_mb,
            "total_gb": round(total_mb / 1024, 2),
            "format_type": format_type,
            "total_frames": total_frames,
        }
