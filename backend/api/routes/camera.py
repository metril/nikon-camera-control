"""
Camera Control API Routes

Endpoints for camera connection and status.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException

from backend.camera.exceptions import CameraConnectionError, CameraNotFoundError
from backend.models.camera import CameraStatus, CameraSummary

router = APIRouter(prefix="/api/camera", tags=["camera"])


# Note: Import controller at runtime to avoid circular imports
def get_controller():
    from backend.main import camera_controller
    return camera_controller


@router.get("/status", response_model=CameraStatus)
async def get_camera_status():
    """
    Get current camera connection status.

    Returns connection state, camera model, and last activity timestamp.
    """
    controller = get_controller()
    status = await controller.get_status()
    return CameraStatus(**status)


@router.post("/connect", response_model=CameraStatus)
async def connect_camera():
    """
    Attempt to connect to the camera.

    The camera must be:
    1. Connected via USB
    2. Powered on
    3. Mode dial set to P, A, S, or M

    Returns:
        Camera status after successful connection.

    Raises:
        404: No camera detected.
        503: Connection failed.
    """
    controller = get_controller()

    try:
        await controller.connect()
        status = await controller.get_status()
        return CameraStatus(**status)

    except CameraNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No Nikon camera detected. Check USB connection and ensure camera is powered on."
        )
    except CameraConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.post("/disconnect")
async def disconnect_camera():
    """
    Disconnect from the camera.

    Safely closes the connection and stops any active operations.
    """
    controller = get_controller()
    await controller.disconnect()

    return {
        "success": True,
        "message": "Camera disconnected",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/summary", response_model=CameraSummary)
async def get_camera_summary():
    """
    Get detailed camera information.

    Returns camera summary including model, firmware version,
    and other device information.

    Raises:
        503: Camera not connected.
    """
    controller = get_controller()

    if not controller.is_connected:
        raise HTTPException(status_code=503, detail="Camera not connected")

    summary = await controller.get_summary()

    if summary is None:
        raise HTTPException(status_code=503, detail="Failed to get camera summary")

    return CameraSummary(summary=summary)


@router.post("/reconnect", response_model=CameraStatus)
async def reconnect_camera():
    """
    Disconnect and reconnect to the camera.

    Useful for recovering from error states.
    """
    controller = get_controller()

    # Disconnect first
    await controller.disconnect()

    # Wait briefly for USB to settle
    import asyncio
    await asyncio.sleep(1.0)

    # Reconnect with retry
    try:
        await controller.connect_with_retry(max_retries=3)
        status = await controller.get_status()
        return CameraStatus(**status)

    except CameraConnectionError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Reconnection failed: {str(e)}"
        )
