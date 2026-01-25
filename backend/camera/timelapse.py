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


# =============================================================================
# Multi-Bracket System (Advanced)
# =============================================================================

@dataclass
class MultiBracketStep:
    """
    A single shot in a multi-bracket sequence.
    Each step can modify multiple settings simultaneously.
    """
    # Dictionary of setting changes for this shot
    # Keys: 'exposurecompensation', 'iso', 'aperture', 'shutterspeed'
    # Values: the target value for each setting
    settings: Dict[str, str] = field(default_factory=dict)

    # Human-readable label for this shot (e.g., "-2EV/ISO100", "Base")
    label: str = ""

    # Optional delay before this shot in ms (for flash recycling, etc.)
    delay_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "settings": self.settings.copy(),
            "label": self.label,
            "delay_ms": self.delay_ms
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MultiBracketStep":
        return cls(
            settings=data.get("settings", {}),
            label=data.get("label", ""),
            delay_ms=data.get("delay_ms", 0)
        )


@dataclass
class MultiBracketConfig:
    """
    Configuration for multi-type bracketing in time-lapse.
    Supports combining multiple bracket types with per-shot control.
    """
    enabled: bool = False

    # Which bracket types are active (for UI state tracking)
    active_types: set = field(default_factory=set)

    # The explicit shot sequence (user-defined or generated from quick-setup)
    steps: List[MultiBracketStep] = field(default_factory=list)

    # Base/reference settings to restore after bracket set
    base_settings: Dict[str, str] = field(default_factory=dict)

    # Mode: 'quick' (generated from toggles) or 'advanced' (user-defined)
    mode: str = "quick"

    # Quick-setup config (stored for regeneration)
    quick_config: Optional[Dict[str, Any]] = None

    @property
    def shots_per_bracket(self) -> int:
        return len(self.steps) if self.steps else 1

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "active_types": [t.value if isinstance(t, BracketType) else t for t in self.active_types],
            "steps": [s.to_dict() for s in self.steps],
            "base_settings": self.base_settings.copy(),
            "mode": self.mode,
            "quick_config": self.quick_config,
            "shots_per_bracket": self.shots_per_bracket
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MultiBracketConfig":
        active = set()
        for t in data.get("active_types", []):
            try:
                active.add(BracketType(t))
            except ValueError:
                pass
        return cls(
            enabled=data.get("enabled", False),
            active_types=active,
            steps=[MultiBracketStep.from_dict(s) for s in data.get("steps", [])],
            base_settings=data.get("base_settings", {}),
            mode=data.get("mode", "quick"),
            quick_config=data.get("quick_config")
        )


@dataclass
class QuickBracketSetup:
    """
    Helper for generating bracket sequences from simple toggle+value inputs.
    Used for the "Quick Setup" UI mode.
    """
    # Each type can be enabled with its own values
    exposure_enabled: bool = False
    exposure_values: List[str] = field(default_factory=lambda: ["-2", "0", "+2"])

    iso_enabled: bool = False
    iso_values: List[str] = field(default_factory=lambda: ["100", "400", "1600"])

    aperture_enabled: bool = False
    aperture_values: List[str] = field(default_factory=lambda: ["f/2.8", "f/5.6", "f/11"])

    shutter_enabled: bool = False
    shutter_values: List[str] = field(default_factory=lambda: ["1/250", "1/125", "1/60"])

    # How to combine: 'sequence' (concatenate) or 'paired' (zip together)
    combine_mode: str = "sequence"

    def to_dict(self) -> dict:
        return {
            "exposure_enabled": self.exposure_enabled,
            "exposure_values": self.exposure_values,
            "iso_enabled": self.iso_enabled,
            "iso_values": self.iso_values,
            "aperture_enabled": self.aperture_enabled,
            "aperture_values": self.aperture_values,
            "shutter_enabled": self.shutter_enabled,
            "shutter_values": self.shutter_values,
            "combine_mode": self.combine_mode
        }

    def get_active_types(self) -> set:
        """Get set of active BracketTypes."""
        active = set()
        if self.exposure_enabled:
            active.add(BracketType.EXPOSURE)
        if self.iso_enabled:
            active.add(BracketType.ISO)
        if self.aperture_enabled:
            active.add(BracketType.APERTURE)
        if self.shutter_enabled:
            active.add(BracketType.SHUTTER)
        return active

    def generate_steps(self) -> List[MultiBracketStep]:
        """
        Generate MultiBracketStep list from quick setup configuration.

        'sequence' mode: Each enabled type adds its own shots
            e.g., 3 EV + 3 ISO = 6 shots (EV1, EV2, EV3, ISO1, ISO2, ISO3)

        'paired' mode: Combine types at same indices (must have same count)
            e.g., 3 EV + 3 ISO = 3 shots (EV1+ISO1, EV2+ISO2, EV3+ISO3)
        """
        steps = []

        if self.combine_mode == "sequence":
            # Concatenate: each type adds sequential shots
            if self.exposure_enabled:
                for val in self.exposure_values:
                    steps.append(MultiBracketStep(
                        settings={"exposurecompensation": val},
                        label=f"{val} EV"
                    ))
            if self.iso_enabled:
                for val in self.iso_values:
                    steps.append(MultiBracketStep(
                        settings={"iso": val},
                        label=f"ISO {val}"
                    ))
            if self.aperture_enabled:
                for val in self.aperture_values:
                    steps.append(MultiBracketStep(
                        settings={"aperture": val},
                        label=val
                    ))
            if self.shutter_enabled:
                for val in self.shutter_values:
                    steps.append(MultiBracketStep(
                        settings={"shutterspeed": val},
                        label=val
                    ))

        elif self.combine_mode == "paired":
            # Paired: combine at same index positions
            enabled_types = []
            if self.exposure_enabled:
                enabled_types.append(("exposurecompensation", self.exposure_values, "EV"))
            if self.iso_enabled:
                enabled_types.append(("iso", self.iso_values, "ISO "))
            if self.aperture_enabled:
                enabled_types.append(("aperture", self.aperture_values, ""))
            if self.shutter_enabled:
                enabled_types.append(("shutterspeed", self.shutter_values, ""))

            if enabled_types:
                max_len = max(len(vals) for _, vals, _ in enabled_types)
                for i in range(max_len):
                    settings = {}
                    labels = []
                    for setting_name, values, prefix in enabled_types:
                        if i < len(values):
                            settings[setting_name] = values[i]
                            labels.append(f"{prefix}{values[i]}")
                    if settings:
                        steps.append(MultiBracketStep(
                            settings=settings,
                            label=" / ".join(labels)
                        ))

        return steps

    def generate_config(self) -> MultiBracketConfig:
        """Generate a MultiBracketConfig from this quick setup."""
        steps = self.generate_steps()
        if not steps:
            return MultiBracketConfig(enabled=False)

        return MultiBracketConfig(
            enabled=True,
            active_types=self.get_active_types(),
            steps=steps,
            mode="quick",
            quick_config=self.to_dict()
        )


# Preset multi-bracket configurations
MULTI_BRACKET_PRESETS = {
    "hdr_3shot": MultiBracketConfig(
        enabled=True,
        active_types={BracketType.EXPOSURE},
        steps=[
            MultiBracketStep(settings={"exposurecompensation": "-2"}, label="-2 EV"),
            MultiBracketStep(settings={"exposurecompensation": "0"}, label="0 EV"),
            MultiBracketStep(settings={"exposurecompensation": "+2"}, label="+2 EV"),
        ],
        mode="advanced"
    ),
    "hdr_5shot": MultiBracketConfig(
        enabled=True,
        active_types={BracketType.EXPOSURE},
        steps=[
            MultiBracketStep(settings={"exposurecompensation": "-2"}, label="-2 EV"),
            MultiBracketStep(settings={"exposurecompensation": "-1"}, label="-1 EV"),
            MultiBracketStep(settings={"exposurecompensation": "0"}, label="0 EV"),
            MultiBracketStep(settings={"exposurecompensation": "+1"}, label="+1 EV"),
            MultiBracketStep(settings={"exposurecompensation": "+2"}, label="+2 EV"),
        ],
        mode="advanced"
    ),
    "hdr_iso_combo": MultiBracketConfig(
        enabled=True,
        active_types={BracketType.EXPOSURE, BracketType.ISO},
        steps=[
            MultiBracketStep(settings={"exposurecompensation": "-2", "iso": "100"}, label="-2EV / ISO100"),
            MultiBracketStep(settings={"exposurecompensation": "0", "iso": "100"}, label="0EV / ISO100"),
            MultiBracketStep(settings={"exposurecompensation": "+2", "iso": "100"}, label="+2EV / ISO100"),
            MultiBracketStep(settings={"exposurecompensation": "0", "iso": "800"}, label="0EV / ISO800"),
        ],
        mode="advanced"
    ),
    "astro_stack": MultiBracketConfig(
        enabled=True,
        active_types={BracketType.ISO},
        steps=[
            MultiBracketStep(settings={"iso": "1600"}, label="ISO 1600"),
            MultiBracketStep(settings={"iso": "3200"}, label="ISO 3200"),
            MultiBracketStep(settings={"iso": "6400"}, label="ISO 6400"),
        ],
        mode="advanced"
    ),
    "aperture_sweep": MultiBracketConfig(
        enabled=True,
        active_types={BracketType.APERTURE},
        steps=[
            MultiBracketStep(settings={"aperture": "2.8"}, label="f/2.8"),
            MultiBracketStep(settings={"aperture": "5.6"}, label="f/5.6"),
            MultiBracketStep(settings={"aperture": "11"}, label="f/11"),
        ],
        mode="advanced"
    ),
}


# Preset bracket configurations (legacy single-type)
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
        self._multi_bracket_config: Optional[MultiBracketConfig] = None  # New multi-bracket system

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

            # Determine which bracket config is active
            bracket_info = None
            if self._is_multi_bracket_active():
                bracket_info = self._multi_bracket_config.to_dict()
            elif self._bracket_config.enabled:
                bracket_info = self._bracket_config.to_dict()

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
                "bracketing": bracket_info,
                "multi_bracket_active": self._is_multi_bracket_active(),
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

        # Determine if any bracketing is active
        bracket_active = (
            (bracket_config and bracket_config.enabled) or
            self._is_multi_bracket_active()
        )

        # Validate interval (higher minimum with bracketing)
        min_interval = 3.0 if bracket_active else 1.0
        if interval_seconds < min_interval:
            raise ValueError(f"Minimum interval is {min_interval}s (higher with bracketing)")

        self._interval_seconds = interval_seconds
        if bracket_config:
            self._bracket_config = bracket_config
            # Disable multi-bracket when legacy bracket is provided
            if bracket_config.enabled:
                self._multi_bracket_config = None

        # Calculate frames from duration or use provided count
        if duration_seconds is not None:
            self._duration_seconds = duration_seconds
            self._total_frames = int(duration_seconds / interval_seconds)
        elif total_frames is not None:
            self._total_frames = total_frames
            self._duration_seconds = int(total_frames * interval_seconds)
        else:
            raise ValueError("Must specify either total_frames or duration_seconds")

        # Estimate disk space (account for both bracket modes)
        if self._is_multi_bracket_active():
            shots_per_interval = self._multi_bracket_config.shots_per_bracket
            bracket_info = self._multi_bracket_config.to_dict()
        elif self._bracket_config.enabled:
            shots_per_interval = self._bracket_config.shots_per_bracket
            bracket_info = self._bracket_config.to_dict()
        else:
            shots_per_interval = 1
            bracket_info = None

        total_shots = self._total_frames * shots_per_interval
        estimated_size_mb = total_shots * 25  # Assume ~25MB per RAW

        return {
            "interval_seconds": self._interval_seconds,
            "total_frames": self._total_frames,
            "duration_seconds": self._duration_seconds,
            "bracketing": bracket_info,
            "multi_bracket_active": self._is_multi_bracket_active(),
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

    # =========================================================================
    # Multi-Bracket Configuration (New)
    # =========================================================================

    def configure_multi_bracket(self, config: MultiBracketConfig) -> MultiBracketConfig:
        """
        Configure multi-type bracketing with explicit shot sequence.

        Args:
            config: MultiBracketConfig with steps defined

        Returns:
            The configured MultiBracketConfig
        """
        if self._state == TimelapseState.RUNNING:
            raise RuntimeError("Cannot configure while time-lapse is running")

        if config.enabled and len(config.steps) < 2:
            raise ValueError("Multi-bracket must have at least 2 steps")

        if config.enabled and len(config.steps) > 15:
            raise ValueError("Multi-bracket limited to 15 steps maximum")

        self._multi_bracket_config = config
        # Disable legacy bracket config when using multi-bracket
        self._bracket_config = BracketConfig(enabled=False)

        return self._multi_bracket_config

    def configure_multi_bracket_quick(self, setup: QuickBracketSetup) -> MultiBracketConfig:
        """
        Configure multi-type bracketing using quick setup toggles.

        Args:
            setup: QuickBracketSetup with type toggles and values

        Returns:
            The generated MultiBracketConfig
        """
        if self._state == TimelapseState.RUNNING:
            raise RuntimeError("Cannot configure while time-lapse is running")

        # Validate at least one type is enabled
        if not any([setup.exposure_enabled, setup.iso_enabled,
                    setup.aperture_enabled, setup.shutter_enabled]):
            raise ValueError("At least one bracket type must be enabled")

        # Generate config
        config = setup.generate_config()

        if len(config.steps) < 2:
            raise ValueError("Quick setup must generate at least 2 shots")

        if len(config.steps) > 15:
            raise ValueError("Quick setup exceeds 15 shot limit")

        self._multi_bracket_config = config
        # Disable legacy bracket config when using multi-bracket
        self._bracket_config = BracketConfig(enabled=False)

        return self._multi_bracket_config

    def configure_multi_bracket_preset(self, preset_name: str) -> MultiBracketConfig:
        """
        Configure multi-bracketing using a preset.

        Args:
            preset_name: Name of preset (hdr_3shot, hdr_5shot, hdr_iso_combo, astro_stack, aperture_sweep)

        Returns:
            The configured MultiBracketConfig
        """
        if preset_name not in MULTI_BRACKET_PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}. Available: {list(MULTI_BRACKET_PRESETS.keys())}")

        self._multi_bracket_config = MULTI_BRACKET_PRESETS[preset_name]
        self._bracket_config = BracketConfig(enabled=False)
        return self._multi_bracket_config

    def disable_multi_bracket(self):
        """Disable multi-bracket mode."""
        self._multi_bracket_config = None

    def get_multi_bracket_preview(self) -> dict:
        """Get preview of current multi-bracket configuration."""
        if not self._multi_bracket_config or not self._multi_bracket_config.enabled:
            return {"enabled": False, "steps": [], "shots_per_bracket": 0}

        return {
            "enabled": True,
            "active_types": [t.value if isinstance(t, BracketType) else t
                           for t in self._multi_bracket_config.active_types],
            "mode": self._multi_bracket_config.mode,
            "shots_per_bracket": self._multi_bracket_config.shots_per_bracket,
            "steps": [
                {
                    "index": i,
                    "label": step.label,
                    "settings": step.settings,
                    "delay_ms": step.delay_ms
                }
                for i, step in enumerate(self._multi_bracket_config.steps)
            ],
            "quick_config": self._multi_bracket_config.quick_config
        }

    @staticmethod
    def get_multi_bracket_presets() -> dict:
        """Get available multi-bracket presets."""
        return {
            name: config.to_dict()
            for name, config in MULTI_BRACKET_PRESETS.items()
        }

    def _is_multi_bracket_active(self) -> bool:
        """Check if multi-bracket mode is active."""
        return (self._multi_bracket_config is not None and
                self._multi_bracket_config.enabled and
                len(self._multi_bracket_config.steps) >= 2)

    async def start(self) -> bool:
        """Start time-lapse capture session."""
        if self._state == TimelapseState.RUNNING:
            return False

        if self._total_frames == 0:
            raise RuntimeError("Time-lapse not configured. Call configure() first.")

        # Create session folder
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"timelapse_{timestamp}"
        if self._is_multi_bracket_active():
            types = "_".join(t.value if isinstance(t, BracketType) else t
                           for t in self._multi_bracket_config.active_types)
            folder_name += f"_multi_{types}"
        elif self._bracket_config.enabled:
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

                if self._is_multi_bracket_active():
                    # Multi-bracket capture (new system)
                    await self._capture_multi_bracket_set()
                elif self._bracket_config.enabled:
                    # Capture bracket set (legacy)
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

    async def _capture_multi_bracket_set(self):
        """Capture a complete multi-bracket set with multiple settings per shot."""
        bracket_files = []

        try:
            for i, step in enumerate(self._multi_bracket_config.steps):
                if self._stop_event.is_set():
                    break

                # Apply optional pre-shot delay
                if step.delay_ms > 0:
                    await asyncio.sleep(step.delay_ms / 1000.0)

                # Apply ALL settings for this step
                if self._settings_callback and step.settings:
                    for setting_name, value in step.settings.items():
                        # Store original on first encounter
                        if setting_name not in self._original_settings:
                            # Store base setting if provided, otherwise use this value
                            base = self._multi_bracket_config.base_settings.get(setting_name)
                            self._original_settings[setting_name] = base if base else value

                        success = await self._settings_callback(setting_name, value)
                        if not success:
                            await self._emit_event("timelapse_warning", {
                                "warning": f"Failed to set {setting_name} to {value}",
                                "bracket_step": i,
                                "step_label": step.label
                            })

                    # Allow camera to apply settings
                    await asyncio.sleep(0.3)

                # Capture
                result = await self._capture_callback()

                if result and result.get("filename"):
                    filename = result["filename"]
                    bracket_files.append(filename)
                    with self._lock:
                        self._frames_captured += 1
                        self._captured_files.append(filename)

                    await self._emit_event("timelapse_multi_bracket_frame", {
                        "frame_number": self._frames_captured,
                        "bracket_step": i,
                        "bracket_label": step.label,
                        "settings_applied": step.settings,
                        "filename": filename,
                        **self.progress
                    })

                # Delay between shots (if not last shot)
                if i < len(self._multi_bracket_config.steps) - 1:
                    await asyncio.sleep(0.5)

            # Record bracket group
            with self._lock:
                self._bracket_sets_captured += 1
                self._bracket_groups.append(bracket_files)

            await self._emit_event("timelapse_multi_bracket_complete", {
                "bracket_set": self._bracket_sets_captured,
                "files": bracket_files,
                "shots_in_set": len(bracket_files),
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
