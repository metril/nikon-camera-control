"""
Time-lapse capture and video generation handler with bracketing support.
"""
import asyncio
import threading
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
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


class BracketType(Enum):
    """Types of bracketing supported."""
    EXPOSURE = "exposure"      # Exposure compensation bracketing
    ISO = "iso"                # ISO bracketing
    APERTURE = "aperture"      # Aperture bracketing
    SHUTTER = "shutter"        # Shutter speed bracketing


@dataclass
class BracketStep:
    """A single step in a bracket sequence."""
    setting_name: str          # Camera setting to modify (e.g., 'exposurecompensation', 'iso')
    value: str                 # Value to set for this step
    label: str = ""            # Human-readable label (e.g., "-2 EV", "ISO 400")


@dataclass
class BracketConfig:
    """Configuration for bracketing in time-lapse."""
    enabled: bool = False
    bracket_type: BracketType = BracketType.EXPOSURE
    shots_per_bracket: int = 3  # 2-9 shots per bracket set
    steps: List[BracketStep] = field(default_factory=list)

    # Common presets
    # Exposure: values are EV compensation (-3 to +3)
    # ISO: actual ISO values (100, 200, 400, etc.)
    # Aperture: f-stop values (f/2.8, f/4, f/5.6, etc.)
    # Shutter: shutter speed values (1/1000, 1/500, 1/250, etc.)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "bracket_type": self.bracket_type.value,
            "shots_per_bracket": self.shots_per_bracket,
            "steps": [{"setting_name": s.setting_name, "value": s.value, "label": s.label} for s in self.steps]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BracketConfig":
        steps = [BracketStep(**s) for s in data.get("steps", [])]
        return cls(
            enabled=data.get("enabled", False),
            bracket_type=BracketType(data.get("bracket_type", "exposure")),
            shots_per_bracket=data.get("shots_per_bracket", 3),
            steps=steps
        )


# Preset bracket configurations
BRACKET_PRESETS = {
    "exposure_3": BracketConfig(
        enabled=True,
        bracket_type=BracketType.EXPOSURE,
        shots_per_bracket=3,
        steps=[
            BracketStep("exposurecompensation", "-2", "-2 EV"),
            BracketStep("exposurecompensation", "0", "0 EV"),
            BracketStep("exposurecompensation", "+2", "+2 EV"),
        ]
    ),
    "exposure_5": BracketConfig(
        enabled=True,
        bracket_type=BracketType.EXPOSURE,
        shots_per_bracket=5,
        steps=[
            BracketStep("exposurecompensation", "-2", "-2 EV"),
            BracketStep("exposurecompensation", "-1", "-1 EV"),
            BracketStep("exposurecompensation", "0", "0 EV"),
            BracketStep("exposurecompensation", "+1", "+1 EV"),
            BracketStep("exposurecompensation", "+2", "+2 EV"),
        ]
    ),
    "exposure_7": BracketConfig(
        enabled=True,
        bracket_type=BracketType.EXPOSURE,
        shots_per_bracket=7,
        steps=[
            BracketStep("exposurecompensation", "-3", "-3 EV"),
            BracketStep("exposurecompensation", "-2", "-2 EV"),
            BracketStep("exposurecompensation", "-1", "-1 EV"),
            BracketStep("exposurecompensation", "0", "0 EV"),
            BracketStep("exposurecompensation", "+1", "+1 EV"),
            BracketStep("exposurecompensation", "+2", "+2 EV"),
            BracketStep("exposurecompensation", "+3", "+3 EV"),
        ]
    ),
    "iso_3": BracketConfig(
        enabled=True,
        bracket_type=BracketType.ISO,
        shots_per_bracket=3,
        steps=[
            BracketStep("iso", "200", "ISO 200"),
            BracketStep("iso", "800", "ISO 800"),
            BracketStep("iso", "3200", "ISO 3200"),
        ]
    ),
}


class TimelapseHandler:
    """
    Handles time-lapse capture sessions with bracketing and video generation.

    Known limitation: Software intervalometer has ±500ms jitter per frame.
    For precise intervals, use camera's built-in intervalometer if available.
    """

    def __init__(
        self,
        capture_callback: Callable,
        settings_callback: Optional[Callable] = None,
        event_callback: Optional[Callable] = None
    ):
        """
        Initialize time-lapse handler.

        Args:
            capture_callback: Async function to call for each capture
            settings_callback: Async function to change camera settings (name, value) -> bool
            event_callback: Optional callback for progress events
        """
        self._capture_callback = capture_callback
        self._settings_callback = settings_callback
        self._event_callback = event_callback

        self._state = TimelapseState.IDLE
        self._lock = threading.Lock()

        # Session configuration
        self._interval_seconds: float = 5.0
        self._total_frames: int = 0
        self._duration_seconds: int = 0
        self._bracket_config: BracketConfig = BracketConfig()

        # Session state
        self._frames_captured: int = 0
        self._bracket_sets_captured: int = 0
        self._captured_files: List[str] = []
        self._bracket_groups: List[List[str]] = []  # Groups of bracketed files
        self._start_time: Optional[datetime] = None
        self._session_folder: Optional[Path] = None
        self._original_settings: Dict[str, str] = {}  # Store original settings for restoration

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

            if self._bracket_config.enabled:
                remaining_sets = max(0, self._total_frames - self._bracket_sets_captured)
                estimated_remaining = remaining_sets * self._interval_seconds
            else:
                remaining_frames = max(0, self._total_frames - self._frames_captured)
                estimated_remaining = remaining_frames * self._interval_seconds

            return {
                "state": self._state.value,
                "frames_captured": self._frames_captured,
                "bracket_sets_captured": self._bracket_sets_captured,
                "total_frames": self._total_frames,
                "interval_seconds": self._interval_seconds,
                "elapsed_seconds": int(elapsed),
                "estimated_remaining_seconds": int(estimated_remaining),
                "captured_files": self._captured_files.copy(),
                "bracket_groups": [list(g) for g in self._bracket_groups],
                "session_folder": str(self._session_folder) if self._session_folder else None,
                "bracketing": self._bracket_config.to_dict(),
            }

    def configure(
        self,
        interval_seconds: float,
        total_frames: Optional[int] = None,
        duration_seconds: Optional[int] = None,
        bracket_config: Optional[BracketConfig] = None
    ) -> dict:
        """
        Configure time-lapse session parameters.

        Args:
            interval_seconds: Seconds between captures/bracket sets (minimum 2s for RAW)
            total_frames: Number of frames/bracket sets to capture
            duration_seconds: Total duration in seconds
            bracket_config: Bracketing configuration (optional)

        Returns:
            Configuration summary with estimated values
        """
        if self._state == TimelapseState.RUNNING:
            raise RuntimeError("Cannot configure while time-lapse is running")

        # Validate interval
        min_interval = 3.0 if bracket_config and bracket_config.enabled else 1.0
        if interval_seconds < min_interval:
            raise ValueError(f"Minimum interval is {min_interval}s (higher with bracketing)")

        self._interval_seconds = interval_seconds
        self._bracket_config = bracket_config or BracketConfig()

        # Calculate frames from duration or use provided count
        if duration_seconds is not None:
            self._duration_seconds = duration_seconds
            self._total_frames = int(duration_seconds / interval_seconds)
        elif total_frames is not None:
            self._total_frames = total_frames
            self._duration_seconds = int(total_frames * interval_seconds)
        else:
            raise ValueError("Must specify either total_frames or duration_seconds")

        # Estimate disk space
        shots_per_interval = self._bracket_config.shots_per_bracket if self._bracket_config.enabled else 1
        total_shots = self._total_frames * shots_per_interval
        estimated_size_mb = total_shots * 25  # Assume ~25MB per RAW

        return {
            "interval_seconds": self._interval_seconds,
            "total_frames": self._total_frames,
            "duration_seconds": self._duration_seconds,
            "bracketing": self._bracket_config.to_dict(),
            "shots_per_interval": shots_per_interval,
            "total_shots": total_shots,
            "estimated_size_mb": estimated_size_mb,
            "estimated_size_gb": round(estimated_size_mb / 1024, 2),
            "estimated_video_duration_30fps": self._total_frames / 30,
            "estimated_video_duration_24fps": self._total_frames / 24,
        }

    def configure_bracket_preset(self, preset_name: str) -> BracketConfig:
        """
        Configure bracketing using a preset.

        Args:
            preset_name: Name of preset (exposure_3, exposure_5, exposure_7, iso_3)

        Returns:
            The configured BracketConfig
        """
        if preset_name not in BRACKET_PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}. Available: {list(BRACKET_PRESETS.keys())}")

        self._bracket_config = BRACKET_PRESETS[preset_name]
        return self._bracket_config

    def configure_custom_bracket(
        self,
        bracket_type: str,
        values: List[str],
        labels: Optional[List[str]] = None
    ) -> BracketConfig:
        """
        Configure custom bracketing.

        Args:
            bracket_type: Type of bracketing (exposure, iso, aperture, shutter)
            values: List of values for each bracket step
            labels: Optional human-readable labels for each step

        Returns:
            The configured BracketConfig
        """
        btype = BracketType(bracket_type)
        setting_map = {
            BracketType.EXPOSURE: "exposurecompensation",
            BracketType.ISO: "iso",
            BracketType.APERTURE: "aperture",
            BracketType.SHUTTER: "shutterspeed",
        }
        setting_name = setting_map[btype]

        if labels is None:
            labels = values

        if len(values) < 2 or len(values) > 9:
            raise ValueError("Bracket must have 2-9 steps")

        steps = [
            BracketStep(setting_name=setting_name, value=v, label=l)
            for v, l in zip(values, labels)
        ]

        self._bracket_config = BracketConfig(
            enabled=True,
            bracket_type=btype,
            shots_per_bracket=len(values),
            steps=steps
        )

        return self._bracket_config

    async def start(self) -> bool:
        """Start time-lapse capture session."""
        if self._state == TimelapseState.RUNNING:
            return False

        if self._total_frames == 0:
            raise RuntimeError("Time-lapse not configured. Call configure() first.")

        # Create session folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"timelapse_{timestamp}"
        if self._bracket_config.enabled:
            folder_name += f"_bracket_{self._bracket_config.bracket_type.value}"
        self._session_folder = Path(settings.media.output_path) / folder_name
        self._session_folder.mkdir(parents=True, exist_ok=True)

        # Reset state
        self._frames_captured = 0
        self._bracket_sets_captured = 0
        self._captured_files = []
        self._bracket_groups = []
        self._original_settings = {}
        self._start_time = datetime.now()
        self._stop_event.clear()
        self._state = TimelapseState.RUNNING

        # Start capture loop
        self._capture_task = asyncio.create_task(self._capture_loop())

        await self._emit_event("timelapse_started", self.progress)
        return True

    async def stop(self) -> dict:
        """Stop time-lapse capture session."""
        if self._state not in (TimelapseState.RUNNING, TimelapseState.PAUSED):
            return self.progress

        self._stop_event.set()
        self._state = TimelapseState.CANCELLED

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass

        # Restore original settings
        await self._restore_original_settings()

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
        """Main capture loop for time-lapse with bracketing support."""
        try:
            while self._bracket_sets_captured < self._total_frames:
                if self._stop_event.is_set():
                    break

                # Wait while paused
                while self._state == TimelapseState.PAUSED:
                    await asyncio.sleep(0.1)
                    if self._stop_event.is_set():
                        return

                capture_start = datetime.now()

                if self._bracket_config.enabled:
                    # Capture bracket set
                    await self._capture_bracket_set()
                else:
                    # Single capture
                    await self._capture_single_frame()

                # Calculate sleep time accounting for capture duration
                capture_duration = (datetime.now() - capture_start).total_seconds()
                sleep_time = max(0, self._interval_seconds - capture_duration)

                if sleep_time > 0 and self._bracket_sets_captured < self._total_frames:
                    await asyncio.sleep(sleep_time)

            # Completed successfully
            if not self._stop_event.is_set():
                await self._restore_original_settings()
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

    async def _capture_single_frame(self):
        """Capture a single frame."""
        try:
            result = await self._capture_callback()

            if result and result.get("filename"):
                filename = result["filename"]
                with self._lock:
                    self._frames_captured += 1
                    self._bracket_sets_captured += 1
                    self._captured_files.append(filename)

                await self._emit_event("timelapse_frame", {
                    "frame_number": self._frames_captured,
                    "filename": filename,
                    **self.progress
                })

        except Exception as e:
            await self._emit_event("timelapse_error", {
                "error": str(e),
                "frame_number": self._frames_captured + 1,
                **self.progress
            })

    async def _capture_bracket_set(self):
        """Capture a complete bracket set."""
        bracket_files = []

        try:
            for i, step in enumerate(self._bracket_config.steps):
                if self._stop_event.is_set():
                    break

                # Change setting for this bracket step
                if self._settings_callback:
                    # Store original value on first use
                    if step.setting_name not in self._original_settings:
                        # We'll restore to the middle value (index len/2)
                        mid_idx = len(self._bracket_config.steps) // 2
                        self._original_settings[step.setting_name] = self._bracket_config.steps[mid_idx].value

                    success = await self._settings_callback(step.setting_name, step.value)
                    if not success:
                        await self._emit_event("timelapse_warning", {
                            "warning": f"Failed to set {step.setting_name} to {step.value}",
                            "bracket_step": i,
                        })

                    # Small delay for camera to apply setting
                    await asyncio.sleep(0.3)

                # Capture
                result = await self._capture_callback()

                if result and result.get("filename"):
                    filename = result["filename"]
                    bracket_files.append(filename)
                    with self._lock:
                        self._frames_captured += 1
                        self._captured_files.append(filename)

                    await self._emit_event("timelapse_bracket_frame", {
                        "frame_number": self._frames_captured,
                        "bracket_step": i,
                        "bracket_label": step.label,
                        "filename": filename,
                        **self.progress
                    })

                # Small delay between bracket shots
                if i < len(self._bracket_config.steps) - 1:
                    await asyncio.sleep(0.5)

            # Record bracket group
            with self._lock:
                self._bracket_sets_captured += 1
                self._bracket_groups.append(bracket_files)

            await self._emit_event("timelapse_bracket_complete", {
                "bracket_set": self._bracket_sets_captured,
                "files": bracket_files,
                **self.progress
            })

        except Exception as e:
            await self._emit_event("timelapse_error", {
                "error": str(e),
                "bracket_set": self._bracket_sets_captured + 1,
                **self.progress
            })

    async def _restore_original_settings(self):
        """Restore camera settings to original values."""
        if self._settings_callback and self._original_settings:
            for setting_name, value in self._original_settings.items():
                try:
                    await self._settings_callback(setting_name, value)
                except Exception:
                    pass  # Best effort restoration

    async def generate_video(
        self,
        output_filename: Optional[str] = None,
        fps: int = 24,
        codec: str = "h264",
        quality: str = "high",
        use_middle_bracket: bool = True
    ) -> Optional[str]:
        """
        Generate video from captured time-lapse frames.

        Args:
            output_filename: Output video filename
            fps: Output video framerate
            codec: Video codec (h264, h265, prores)
            quality: Quality preset (low, medium, high)
            use_middle_bracket: If bracketing, use middle exposure for video

        Returns:
            Path to generated video file
        """
        if not self._captured_files:
            raise RuntimeError("No frames captured for video generation")

        if not self._session_folder or not self._session_folder.exists():
            raise RuntimeError("Session folder not found")

        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg not found. Install FFmpeg to generate videos.")

        self._state = TimelapseState.GENERATING
        await self._emit_event("timelapse_generating", {"fps": fps, "codec": codec})

        # Select frames for video
        if self._bracket_config.enabled and self._bracket_groups:
            # Use middle frame from each bracket set
            if use_middle_bracket:
                mid_idx = len(self._bracket_config.steps) // 2
                frames_for_video = [
                    group[mid_idx] for group in self._bracket_groups
                    if len(group) > mid_idx
                ]
            else:
                # Use all frames (will result in "flickery" video showing bracket sequence)
                frames_for_video = self._captured_files
        else:
            frames_for_video = self._captured_files

        if not frames_for_video:
            raise RuntimeError("No frames available for video")

        # Determine output filename
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "mov" if codec == "prores" else "mp4"
            output_filename = f"timelapse_{timestamp}.{ext}"

        output_path = Path(settings.media.output_path) / output_filename

        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(frames_for_video, fps, codec, quality, output_path)

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
                "codec": codec,
                "frames_used": len(frames_for_video)
            })

            return str(output_path)

        except Exception as e:
            self._state = TimelapseState.ERROR
            await self._emit_event("timelapse_error", {"error": str(e)})
            raise

    def _build_ffmpeg_command(
        self,
        frames: List[str],
        fps: int,
        codec: str,
        quality: str,
        output_path: Path
    ) -> List[str]:
        """Build FFmpeg command for video generation."""
        file_list_path = self._session_folder / "filelist.txt"
        with open(file_list_path, "w") as f:
            for filename in frames:
                filepath = Path(settings.media.output_path) / filename
                if filepath.exists():
                    f.write(f"file '{filepath}'\n")
                    f.write(f"duration {1/fps}\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list_path),
        ]

        quality_map = {
            "low": {"h264": "28", "h265": "30", "prores": "3"},
            "medium": {"h264": "23", "h265": "25", "prores": "2"},
            "high": {"h264": "18", "h265": "20", "prores": "1"},
        }

        if codec == "h264":
            crf = quality_map[quality]["h264"]
            cmd.extend(["-c:v", "libx264", "-crf", crf, "-preset", "slow", "-pix_fmt", "yuv420p"])
        elif codec == "h265":
            crf = quality_map[quality]["h265"]
            cmd.extend(["-c:v", "libx265", "-crf", crf, "-preset", "slow", "-pix_fmt", "yuv420p"])
        elif codec == "prores":
            profile = quality_map[quality]["prores"]
            cmd.extend(["-c:v", "prores_ks", "-profile:v", profile, "-pix_fmt", "yuv422p10le"])

        cmd.extend(["-r", str(fps), str(output_path)])
        return cmd

    async def _emit_event(self, event_type: str, data: dict):
        """Emit event via callback."""
        if self._event_callback:
            try:
                await self._event_callback(event_type, data)
            except Exception:
                pass

    def get_disk_space_estimate(
        self,
        total_frames: int,
        format_type: str = "raw",
        bracket_shots: int = 1
    ) -> dict:
        """Estimate disk space required."""
        size_per_frame_mb = {
            "raw": 45,
            "raw_compressed": 25,
            "jpeg_fine": 12,
            "jpeg_normal": 6,
            "jpeg_basic": 3,
        }

        frame_size = size_per_frame_mb.get(format_type, 25)
        total_shots = total_frames * bracket_shots
        total_mb = total_shots * frame_size

        return {
            "frame_size_mb": frame_size,
            "total_shots": total_shots,
            "total_mb": total_mb,
            "total_gb": round(total_mb / 1024, 2),
            "format_type": format_type,
            "total_frames": total_frames,
            "bracket_shots": bracket_shots,
        }

    @staticmethod
    def get_bracket_presets() -> dict:
        """Get available bracket presets."""
        return {
            name: config.to_dict()
            for name, config in BRACKET_PRESETS.items()
        }
