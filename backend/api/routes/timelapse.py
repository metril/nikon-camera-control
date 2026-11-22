"""
Time-lapse API routes with bracketing support.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict

from backend.camera.timelapse import (
    BracketConfig, BracketStep, BracketType,
    MultiBracketConfig, MultiBracketStep, QuickBracketSetup
)

router = APIRouter(prefix="/api/timelapse", tags=["timelapse"])


# =============================================================================
# Request/Response Models
# =============================================================================

class BracketStepModel(BaseModel):
    """A single step in a bracket sequence."""
    setting_name: str = Field(..., description="Camera setting to modify")
    value: str = Field(..., description="Value to set for this step")
    label: str = Field("", description="Human-readable label")


class BracketConfigModel(BaseModel):
    """Bracketing configuration."""
    enabled: bool = Field(False, description="Enable bracketing")
    bracket_type: str = Field("exposure", pattern="^(exposure|iso|aperture|shutter)$")
    shots_per_bracket: int = Field(3, ge=2, le=9, description="Shots per bracket set")
    steps: List[BracketStepModel] = Field(default_factory=list)

    def to_bracket_config(self) -> BracketConfig:
        """Convert to internal BracketConfig."""
        steps = [BracketStep(s.setting_name, s.value, s.label) for s in self.steps]
        return BracketConfig(
            enabled=self.enabled,
            bracket_type=BracketType(self.bracket_type),
            shots_per_bracket=self.shots_per_bracket,
            steps=steps
        )


class TimelapseConfig(BaseModel):
    """Time-lapse configuration request."""
    interval_seconds: float = Field(..., ge=1.0, description="Seconds between captures/bracket sets")
    total_frames: Optional[int] = Field(None, ge=1, description="Total number of frames/bracket sets")
    duration_seconds: Optional[int] = Field(None, ge=1, description="Total duration in seconds")
    bracket_config: Optional[BracketConfigModel] = Field(None, description="Bracketing configuration")


class BracketPresetConfig(BaseModel):
    """Configure bracketing from a preset."""
    preset_name: str = Field(..., description="Preset name (exposure_3, exposure_5, exposure_7, iso_3)")


class CustomBracketConfig(BaseModel):
    """Configure custom bracketing."""
    bracket_type: str = Field(..., pattern="^(exposure|iso|aperture|shutter)$")
    values: List[str] = Field(..., min_length=2, max_length=9)
    labels: Optional[List[str]] = Field(None, description="Human-readable labels for each value")


class VideoGenerationConfig(BaseModel):
    """Video generation configuration."""
    output_filename: Optional[str] = None
    fps: int = Field(24, ge=1, le=60)
    codec: str = Field("h264", pattern="^(h264|h265|prores)$")
    quality: str = Field("high", pattern="^(low|medium|high)$")
    use_middle_bracket: bool = Field(True, description="Use middle exposure from bracket sets for video")


class DiskSpaceRequest(BaseModel):
    """Disk space estimation request."""
    total_frames: int = Field(..., ge=1)
    format_type: str = Field("raw", pattern="^(raw|raw_compressed|jpeg_fine|jpeg_normal|jpeg_basic)$")
    bracket_shots: int = Field(1, ge=1, le=15, description="Shots per bracket set")


# =============================================================================
# Multi-Bracket Models (New)
# =============================================================================

class MultiBracketStepModel(BaseModel):
    """A single shot in a multi-bracket sequence."""
    settings: Dict[str, str] = Field(
        default_factory=dict,
        description="Setting name to value mapping for this shot (e.g., {'exposurecompensation': '-2', 'iso': '100'})"
    )
    label: str = Field("", description="Human-readable label")
    delay_ms: int = Field(0, ge=0, le=5000, description="Delay before shot in ms")

    def to_multi_bracket_step(self) -> MultiBracketStep:
        return MultiBracketStep(
            settings=self.settings,
            label=self.label,
            delay_ms=self.delay_ms
        )


class MultiBracketConfigModel(BaseModel):
    """Multi-type bracketing configuration."""
    enabled: bool = Field(True)
    active_types: List[str] = Field(
        default_factory=list,
        description="Active bracket types: exposure, iso, aperture, shutter"
    )
    steps: List[MultiBracketStepModel] = Field(
        ...,
        min_length=2,
        max_length=15,
        description="Shot sequence (2-15 steps)"
    )
    base_settings: Dict[str, str] = Field(
        default_factory=dict,
        description="Base settings to restore after bracket set"
    )

    def to_multi_bracket_config(self) -> MultiBracketConfig:
        active = set()
        for t in self.active_types:
            try:
                active.add(BracketType(t))
            except ValueError:
                pass
        return MultiBracketConfig(
            enabled=self.enabled,
            active_types=active,
            steps=[s.to_multi_bracket_step() for s in self.steps],
            base_settings=self.base_settings,
            mode="advanced"
        )


class QuickBracketSetupModel(BaseModel):
    """Quick setup for generating bracket sequences."""
    exposure_enabled: bool = Field(False, description="Enable exposure bracketing")
    exposure_values: List[str] = Field(
        default_factory=lambda: ["-2", "0", "+2"],
        description="Exposure compensation values"
    )
    iso_enabled: bool = Field(False, description="Enable ISO bracketing")
    iso_values: List[str] = Field(
        default_factory=lambda: ["100", "400", "1600"],
        description="ISO values"
    )
    aperture_enabled: bool = Field(False, description="Enable aperture bracketing")
    aperture_values: List[str] = Field(
        default_factory=lambda: ["2.8", "5.6", "11"],
        description="Aperture values (without f/ prefix)"
    )
    shutter_enabled: bool = Field(False, description="Enable shutter speed bracketing")
    shutter_values: List[str] = Field(
        default_factory=lambda: ["1/250", "1/125", "1/60"],
        description="Shutter speed values"
    )
    combine_mode: str = Field(
        "sequence",
        pattern="^(sequence|paired)$",
        description="How to combine types: 'sequence' (concatenate) or 'paired' (zip)"
    )

    def to_quick_bracket_setup(self) -> QuickBracketSetup:
        return QuickBracketSetup(
            exposure_enabled=self.exposure_enabled,
            exposure_values=self.exposure_values,
            iso_enabled=self.iso_enabled,
            iso_values=self.iso_values,
            aperture_enabled=self.aperture_enabled,
            aperture_values=self.aperture_values,
            shutter_enabled=self.shutter_enabled,
            shutter_values=self.shutter_values,
            combine_mode=self.combine_mode
        )


class MultiBracketPresetConfig(BaseModel):
    """Configure multi-bracketing from a preset."""
    preset_name: str = Field(
        ...,
        description="Preset name (hdr_3shot, hdr_5shot, hdr_iso_combo, astro_stack, aperture_sweep)"
    )


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/status")
async def get_timelapse_status():
    """Get current time-lapse status and progress."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    return timelapse_handler.progress


@router.get("/bracket-presets")
async def get_bracket_presets():
    """Get available bracket presets."""
    from backend.camera.timelapse import TimelapseHandler
    return TimelapseHandler.get_bracket_presets()


@router.post("/configure")
async def configure_timelapse(config: TimelapseConfig):
    """
    Configure time-lapse session parameters.

    Either total_frames or duration_seconds must be provided.
    Minimum interval is 1s without bracketing, 3s with bracketing.
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    if config.total_frames is None and config.duration_seconds is None:
        raise HTTPException(
            status_code=400,
            detail="Must specify either total_frames or duration_seconds"
        )

    try:
        bracket_config = config.bracket_config.to_bracket_config() if config.bracket_config else None

        result = timelapse_handler.configure(
            interval_seconds=config.interval_seconds,
            total_frames=config.total_frames,
            duration_seconds=config.duration_seconds,
            bracket_config=bracket_config
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/configure/bracket-preset")
async def configure_bracket_preset(config: BracketPresetConfig):
    """
    Configure bracketing using a preset.

    Available presets: exposure_3, exposure_5, exposure_7, iso_3
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        bracket_config = timelapse_handler.configure_bracket_preset(config.preset_name)
        return bracket_config.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/configure/bracket-custom")
async def configure_custom_bracket(config: CustomBracketConfig):
    """
    Configure custom bracketing with specific values.

    Examples:
    - Exposure: values=["-2", "-1", "0", "+1", "+2"]
    - ISO: values=["100", "400", "1600", "6400"]
    - Aperture: values=["f/2.8", "f/4", "f/5.6", "f/8"]
    - Shutter: values=["1/1000", "1/500", "1/250", "1/125"]
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        bracket_config = timelapse_handler.configure_custom_bracket(
            bracket_type=config.bracket_type,
            values=config.values,
            labels=config.labels
        )
        return bracket_config.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/configure/bracket-disable")
async def disable_bracketing():
    """Disable bracketing for time-lapse."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    timelapse_handler._bracket_config = BracketConfig(enabled=False)
    return {"enabled": False}


@router.post("/start")
async def start_timelapse():
    """Start time-lapse capture session."""
    from backend.main import timelapse_handler, camera_controller

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    if not camera_controller.is_connected:
        raise HTTPException(status_code=409, detail="Camera not connected")

    try:
        success = await timelapse_handler.start()
        if not success:
            raise HTTPException(status_code=409, detail="Time-lapse already running")
        return {"status": "started", **timelapse_handler.progress}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stop")
async def stop_timelapse():
    """Stop time-lapse capture session."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    result = await timelapse_handler.stop()
    return {"status": "stopped", **result}


@router.post("/pause")
async def pause_timelapse():
    """Pause time-lapse capture session."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    success = await timelapse_handler.pause()
    if not success:
        raise HTTPException(status_code=409, detail="Time-lapse not running")
    return {"status": "paused", **timelapse_handler.progress}


@router.post("/resume")
async def resume_timelapse():
    """Resume paused time-lapse capture session."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    success = await timelapse_handler.resume()
    if not success:
        raise HTTPException(status_code=409, detail="Time-lapse not paused")
    return {"status": "running", **timelapse_handler.progress}


@router.post("/generate-video")
async def generate_video(config: VideoGenerationConfig):
    """
    Generate video from captured time-lapse frames.

    With bracketing, by default uses the middle exposure from each bracket set.
    Set use_middle_bracket=false to use all frames (creates flickery bracket sequence video).
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        video_path = await timelapse_handler.generate_video(
            output_filename=config.output_filename,
            fps=config.fps,
            codec=config.codec,
            quality=config.quality,
            use_middle_bracket=config.use_middle_bracket
        )
        return {
            "status": "completed",
            "video_path": video_path,
            "fps": config.fps,
            "codec": config.codec,
            "quality": config.quality,
            "use_middle_bracket": config.use_middle_bracket
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/estimate-disk-space")
async def estimate_disk_space(request: DiskSpaceRequest):
    """
    Estimate disk space required for time-lapse session.

    Include bracket_shots to account for bracketing (e.g., 3 for 3-shot bracket).
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    return timelapse_handler.get_disk_space_estimate(
        total_frames=request.total_frames,
        format_type=request.format_type,
        bracket_shots=request.bracket_shots
    )


# =============================================================================
# Multi-Bracket Endpoints (New)
# =============================================================================

@router.get("/multi-bracket/presets")
async def get_multi_bracket_presets():
    """
    Get available multi-bracket presets.

    Available presets:
    - hdr_3shot: 3-shot exposure bracket (-2, 0, +2 EV)
    - hdr_5shot: 5-shot exposure bracket (-2, -1, 0, +1, +2 EV)
    - hdr_iso_combo: HDR + ISO bracket combo (4 shots)
    - astro_stack: ISO stacking for astrophotography
    - aperture_sweep: Aperture sweep for focus stacking
    """
    from backend.camera.timelapse import TimelapseHandler
    return TimelapseHandler.get_multi_bracket_presets()


@router.get("/multi-bracket/preview")
async def get_multi_bracket_preview():
    """Get preview of current multi-bracket configuration."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    return timelapse_handler.get_multi_bracket_preview()


@router.post("/configure/multi-bracket")
async def configure_multi_bracket(config: MultiBracketConfigModel):
    """
    Configure advanced multi-type bracketing with explicit shot sequence.

    Each step defines settings to apply before that shot.
    Multiple settings can be combined (e.g., exposure + ISO).

    Example:
    ```json
    {
        "enabled": true,
        "active_types": ["exposure", "iso"],
        "steps": [
            {"settings": {"exposurecompensation": "-2", "iso": "100"}, "label": "-2EV / ISO100"},
            {"settings": {"exposurecompensation": "0", "iso": "100"}, "label": "0EV / ISO100"},
            {"settings": {"exposurecompensation": "+2", "iso": "100"}, "label": "+2EV / ISO100"},
            {"settings": {"exposurecompensation": "0", "iso": "800"}, "label": "0EV / ISO800"}
        ]
    }
    ```
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        multi_config = config.to_multi_bracket_config()
        result = timelapse_handler.configure_multi_bracket(multi_config)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/configure/multi-bracket/quick")
async def configure_multi_bracket_quick(setup: QuickBracketSetupModel):
    """
    Configure multi-type bracketing using quick setup toggles.

    Enable bracket types independently and provide values for each.
    Steps are auto-generated based on combine_mode:

    - 'sequence': Each type adds sequential shots
      e.g., 3 EV + 3 ISO = 6 shots (EV1, EV2, EV3, ISO1, ISO2, ISO3)

    - 'paired': Combine types at same indices
      e.g., 3 EV + 3 ISO = 3 shots (EV1+ISO1, EV2+ISO2, EV3+ISO3)

    Example:
    ```json
    {
        "exposure_enabled": true,
        "exposure_values": ["-2", "0", "+2"],
        "iso_enabled": true,
        "iso_values": ["100", "400", "1600"],
        "combine_mode": "sequence"
    }
    ```
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        quick_setup = setup.to_quick_bracket_setup()
        result = timelapse_handler.configure_multi_bracket_quick(quick_setup)
        return {
            **result.to_dict(),
            "generated_steps": [
                {"index": i, "label": s.label, "settings": s.settings}
                for i, s in enumerate(result.steps)
            ]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/configure/multi-bracket/preset")
async def configure_multi_bracket_preset(config: MultiBracketPresetConfig):
    """
    Configure multi-bracketing using a preset.

    Available presets:
    - hdr_3shot: 3-shot exposure bracket (-2, 0, +2 EV)
    - hdr_5shot: 5-shot exposure bracket (-2, -1, 0, +1, +2 EV)
    - hdr_iso_combo: HDR + ISO bracket combo
    - astro_stack: ISO stacking for astrophotography
    - aperture_sweep: Aperture sweep for focus stacking
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        result = timelapse_handler.configure_multi_bracket_preset(config.preset_name)
        return result.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/configure/multi-bracket/disable")
async def disable_multi_bracket():
    """Disable multi-bracket mode."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    timelapse_handler.disable_multi_bracket()
    return {"enabled": False, "multi_bracket_active": False}
