"""
Time-lapse API routes.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/timelapse", tags=["timelapse"])


class TimelapseConfig(BaseModel):
    """Time-lapse configuration request."""
    interval_seconds: float = Field(..., ge=1.0, description="Seconds between captures")
    total_frames: Optional[int] = Field(None, ge=1, description="Total number of frames")
    duration_seconds: Optional[int] = Field(None, ge=1, description="Total duration in seconds")


class VideoGenerationConfig(BaseModel):
    """Video generation configuration."""
    output_filename: Optional[str] = None
    fps: int = Field(24, ge=1, le=60)
    codec: str = Field("h264", pattern="^(h264|h265|prores)$")
    quality: str = Field("high", pattern="^(low|medium|high)$")


class DiskSpaceRequest(BaseModel):
    """Disk space estimation request."""
    total_frames: int = Field(..., ge=1)
    format_type: str = Field("raw", pattern="^(raw|raw_compressed|jpeg_fine|jpeg_normal|jpeg_basic)$")


@router.get("/status")
async def get_timelapse_status():
    """Get current time-lapse status and progress."""
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    return timelapse_handler.progress


@router.post("/configure")
async def configure_timelapse(config: TimelapseConfig):
    """
    Configure time-lapse session parameters.

    Either total_frames or duration_seconds must be provided.
    Minimum interval is 1 second (2 seconds recommended for RAW captures).
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
        result = timelapse_handler.configure(
            interval_seconds=config.interval_seconds,
            total_frames=config.total_frames,
            duration_seconds=config.duration_seconds
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


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

    Requires FFmpeg to be installed.
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    try:
        video_path = await timelapse_handler.generate_video(
            output_filename=config.output_filename,
            fps=config.fps,
            codec=config.codec,
            quality=config.quality
        )
        return {
            "status": "completed",
            "video_path": video_path,
            "fps": config.fps,
            "codec": config.codec,
            "quality": config.quality
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/estimate-disk-space")
async def estimate_disk_space(request: DiskSpaceRequest):
    """
    Estimate disk space required for time-lapse session.

    Provides estimates based on D500 typical file sizes.
    """
    from backend.main import timelapse_handler

    if timelapse_handler is None:
        raise HTTPException(status_code=503, detail="Time-lapse handler not initialized")

    return timelapse_handler.get_disk_space_estimate(
        total_frames=request.total_frames,
        format_type=request.format_type
    )
