"""
Time-lapse API routes with bracketing support.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from backend.camera.timelapse import BracketConfig, BracketStep, BracketType

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
    bracket_shots: int = Field(1, ge=1, le=9, description="Shots per bracket set")


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

    if not camera_controller.connected:
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
