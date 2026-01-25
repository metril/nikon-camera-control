"""
Camera Settings API Routes

Endpoints for reading and modifying camera settings.
"""

from fastapi import APIRouter, HTTPException

from backend.camera.controller import CameraController
from backend.camera.exceptions import (
    CameraDisconnectedError,
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingValueError,
)
from backend.camera.settings import CameraSettingsManager
from backend.models.camera import (
    CameraSetting,
    SetSettingRequest,
    SetSettingResponse,
    SettingsResponse,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def get_settings_manager(controller: CameraController) -> CameraSettingsManager:
    """Get settings manager from controller."""
    if not controller.is_connected:
        raise HTTPException(status_code=503, detail="Camera not connected")

    return CameraSettingsManager(
        controller._camera,
        controller._context,
        controller._lock
    )


# Note: In production, use dependency injection for the controller
# For now, import the global instance
from backend.main import camera_controller


@router.get("", response_model=SettingsResponse)
async def get_all_settings():
    """
    Get all available camera settings.

    Returns all settings discovered on the camera, including
    their current values and available options.
    """
    manager = get_settings_manager(camera_controller)
    settings = await manager.get_all_settings()

    # Convert to response format
    settings_dict = {
        name: CameraSetting(**setting.to_dict())
        for name, setting in settings.items()
    }

    return SettingsResponse(settings=settings_dict, count=len(settings_dict))


@router.get("/common", response_model=SettingsResponse)
async def get_common_settings():
    """
    Get commonly used camera settings.

    Returns only the most frequently used settings for quick access:
    - ISO, Aperture, Shutter Speed
    - Focus Mode, White Balance
    - Image Format, Metering Mode
    - Battery Level
    """
    manager = get_settings_manager(camera_controller)
    settings = await manager.get_common_settings()

    settings_dict = {
        name: CameraSetting(**setting.to_dict())
        for name, setting in settings.items()
    }

    return SettingsResponse(settings=settings_dict, count=len(settings_dict))


@router.get("/{name}", response_model=CameraSetting)
async def get_setting(name: str):
    """
    Get a specific camera setting.

    Args:
        name: Setting name (e.g., "iso", "aperture", "shutterspeed")

    Returns:
        Current value and available options for the setting.

    Raises:
        404: Setting not found on this camera.
    """
    manager = get_settings_manager(camera_controller)

    try:
        setting = await manager.get_setting(name)
        return CameraSetting(**setting.to_dict())
    except SettingNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Setting '{name}' not found on this camera"
        )


@router.put("/{name}", response_model=SetSettingResponse)
async def set_setting(name: str, request: SetSettingRequest):
    """
    Set a camera setting value.

    Args:
        name: Setting name
        request: New value to set

    Returns:
        Updated setting value.

    Raises:
        400: Invalid value for the setting.
        403: Setting is read-only (check camera mode dial).
        404: Setting not found.
    """
    manager = get_settings_manager(camera_controller)

    try:
        updated = await manager.set_setting(name, request.value)
        return SetSettingResponse(
            success=True,
            setting=CameraSetting(**updated.to_dict()),
            message=f"Successfully set {name} to {request.value}"
        )

    except SettingNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Setting '{name}' not found on this camera"
        )

    except SettingReadOnlyError as e:
        raise HTTPException(
            status_code=403,
            detail=str(e.message)
        )

    except SettingValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e.message)
        )


@router.get("/battery/level")
async def get_battery_level():
    """
    Get current battery level.

    Returns:
        Battery percentage (0-100) or null if not available.
    """
    manager = get_settings_manager(camera_controller)
    level = await manager.get_battery_level()

    return {
        "battery_level": level,
        "unit": "percent" if level is not None else None,
    }


# =============================================================================
# Convenience Endpoints for Common Settings
# =============================================================================

@router.get("/exposure/iso", response_model=CameraSetting)
async def get_iso():
    """Get current ISO setting."""
    return await get_setting("iso")


@router.put("/exposure/iso", response_model=SetSettingResponse)
async def set_iso(request: SetSettingRequest):
    """Set ISO value (e.g., "100", "400", "3200")."""
    return await set_setting("iso", request)


@router.get("/exposure/aperture", response_model=CameraSetting)
async def get_aperture():
    """Get current aperture setting."""
    return await get_setting("aperture")


@router.put("/exposure/aperture", response_model=SetSettingResponse)
async def set_aperture(request: SetSettingRequest):
    """Set aperture value (e.g., "f/2.8", "f/5.6")."""
    return await set_setting("aperture", request)


@router.get("/exposure/shutterspeed", response_model=CameraSetting)
async def get_shutter_speed():
    """Get current shutter speed setting."""
    return await get_setting("shutterspeed")


@router.put("/exposure/shutterspeed", response_model=SetSettingResponse)
async def set_shutter_speed(request: SetSettingRequest):
    """Set shutter speed value (e.g., "1/500", "1/60", "1")."""
    return await set_setting("shutterspeed", request)


@router.get("/focus/mode", response_model=CameraSetting)
async def get_focus_mode():
    """Get current focus mode (AF-S, AF-C, MF)."""
    return await get_setting("focusmode")


@router.put("/focus/mode", response_model=SetSettingResponse)
async def set_focus_mode(request: SetSettingRequest):
    """Set focus mode (e.g., "AF-S", "AF-C", "Manual")."""
    return await set_setting("focusmode", request)


@router.get("/image/whitebalance", response_model=CameraSetting)
async def get_white_balance():
    """Get current white balance setting."""
    return await get_setting("whitebalance")


@router.put("/image/whitebalance", response_model=SetSettingResponse)
async def set_white_balance(request: SetSettingRequest):
    """Set white balance preset (e.g., "Daylight", "Cloudy", "Flash")."""
    return await set_setting("whitebalance", request)


@router.get("/image/format", response_model=CameraSetting)
async def get_image_format():
    """Get current image format/quality setting."""
    return await get_setting("imageformat")


@router.put("/image/format", response_model=SetSettingResponse)
async def set_image_format(request: SetSettingRequest):
    """Set image format (e.g., "RAW", "JPEG Fine", "RAW + JPEG")."""
    return await set_setting("imageformat", request)
