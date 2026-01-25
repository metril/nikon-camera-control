"""
Camera Settings Manager

Handles discovery and modification of camera settings via PTP/gphoto2.

IMPORTANT NOTES:
- Settings behavior depends on camera mode dial position (P/A/S/M)
- Some settings are read-only depending on the mode
- Changes may silently fail if mode dial is in Auto/Scene modes
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import structlog

from backend.camera.exceptions import (
    CameraDisconnectedError,
    SettingNotFoundError,
    SettingReadOnlyError,
    SettingValueError,
)

# Try to import gphoto2
try:
    import gphoto2 as gp
    GPHOTO2_AVAILABLE = True
except ImportError:
    gp = None
    GPHOTO2_AVAILABLE = False

logger = structlog.get_logger(__name__)


class SettingType(Enum):
    """Types of camera settings."""
    RADIO = "radio"       # Single selection from list
    MENU = "menu"         # Menu selection
    TEXT = "text"         # Free-form text
    RANGE = "range"       # Numeric range (min, max, step)
    TOGGLE = "toggle"     # On/off boolean
    DATE = "date"         # Date/time
    SECTION = "section"   # Container for other settings
    UNKNOWN = "unknown"


@dataclass
class CameraSetting:
    """Represents a camera setting with current value and options."""
    name: str
    label: str
    path: str
    type: SettingType
    value: Any
    readonly: bool = False
    choices: list[str] = field(default_factory=list)
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    range_step: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "name": self.name,
            "label": self.label,
            "path": self.path,
            "type": self.type.value,
            "value": self.value,
            "readonly": self.readonly,
        }
        if self.choices:
            result["choices"] = self.choices
        if self.range_min is not None:
            result["range"] = {
                "min": self.range_min,
                "max": self.range_max,
                "step": self.range_step,
            }
        return result


# Common Nikon D500 settings paths
# These are the most commonly used settings for remote control
COMMON_SETTINGS = {
    # Exposure settings
    "iso": "/main/imgsettings/iso",
    "aperture": "/main/capturesettings/f-number",
    "shutterspeed": "/main/capturesettings/shutterspeed",
    "exposurecompensation": "/main/capturesettings/exposurecompensation",
    "autoexposuremode": "/main/capturesettings/autoexposuremode",

    # Focus settings
    "focusmode": "/main/capturesettings/focusmode",
    "autofocusdrive": "/main/actions/autofocusdrive",

    # Image settings
    "whitebalance": "/main/imgsettings/whitebalance",
    "imageformat": "/main/imgsettings/imagequality",
    "imagesize": "/main/imgsettings/imagesize",

    # Live view
    "liveviewsize": "/main/capturesettings/liveviewsize",
    "viewfinder": "/main/actions/viewfinder",

    # Capture target
    "capturetarget": "/main/capturesettings/capturetarget",

    # Metering
    "meteringmode": "/main/capturesettings/meteringmode",

    # Battery
    "batterylevel": "/main/status/batterylevel",
}


class CameraSettingsManager:
    """
    Manages camera settings discovery and modification.

    Usage:
        manager = CameraSettingsManager(camera, context, lock)
        settings = await manager.get_all_settings()
        await manager.set_setting("iso", "400")
    """

    def __init__(self, camera, context, lock):
        """
        Initialize settings manager.

        Args:
            camera: gphoto2 Camera object
            context: gphoto2 Context object
            lock: threading.Lock for thread-safe access
        """
        self._camera = camera
        self._context = context
        self._lock = lock
        self._settings_cache: Optional[dict[str, CameraSetting]] = None

    def _get_widget_type(self, widget) -> SettingType:
        """Convert gphoto2 widget type to SettingType."""
        if not GPHOTO2_AVAILABLE:
            return SettingType.UNKNOWN

        widget_type = widget.get_type()
        type_map = {
            gp.GP_WIDGET_RADIO: SettingType.RADIO,
            gp.GP_WIDGET_MENU: SettingType.MENU,
            gp.GP_WIDGET_TEXT: SettingType.TEXT,
            gp.GP_WIDGET_RANGE: SettingType.RANGE,
            gp.GP_WIDGET_TOGGLE: SettingType.TOGGLE,
            gp.GP_WIDGET_DATE: SettingType.DATE,
            gp.GP_WIDGET_SECTION: SettingType.SECTION,
            gp.GP_WIDGET_WINDOW: SettingType.SECTION,
        }
        return type_map.get(widget_type, SettingType.UNKNOWN)

    def _widget_to_setting(self, widget, path: str = "") -> Optional[CameraSetting]:
        """Convert a gphoto2 widget to a CameraSetting object."""
        if not GPHOTO2_AVAILABLE:
            return None

        widget_type = self._get_widget_type(widget)

        # Skip section/window types
        if widget_type == SettingType.SECTION:
            return None

        name = widget.get_name()
        label = widget.get_label()
        readonly = widget.get_readonly() != 0

        # Get value
        try:
            value = widget.get_value()
        except gp.GPhoto2Error:
            value = None

        # Get choices for radio/menu types
        choices = []
        if widget_type in (SettingType.RADIO, SettingType.MENU):
            for i in range(widget.count_choices()):
                try:
                    choices.append(widget.get_choice(i))
                except gp.GPhoto2Error:
                    break

        # Get range for range type
        range_min = range_max = range_step = None
        if widget_type == SettingType.RANGE:
            try:
                range_min, range_max, range_step = widget.get_range()
            except gp.GPhoto2Error:
                pass

        return CameraSetting(
            name=name,
            label=label,
            path=path or f"/{name}",
            type=widget_type,
            value=value,
            readonly=readonly,
            choices=choices,
            range_min=range_min,
            range_max=range_max,
            range_step=range_step,
        )

    def _walk_config(
        self,
        widget,
        settings: dict[str, CameraSetting],
        path: str = ""
    ) -> None:
        """Recursively walk the config tree to extract all settings."""
        for i in range(widget.count_children()):
            child = widget.get_child(i)
            child_path = f"{path}/{child.get_name()}"

            setting = self._widget_to_setting(child, child_path)
            if setting:
                settings[child.get_name()] = setting

            # Recurse into children
            if child.count_children() > 0:
                self._walk_config(child, settings, child_path)

    async def get_all_settings(self, use_cache: bool = False) -> dict[str, CameraSetting]:
        """
        Get all available camera settings.

        Args:
            use_cache: If True, return cached settings if available.

        Returns:
            Dictionary of setting name to CameraSetting objects.
        """
        if use_cache and self._settings_cache:
            return self._settings_cache

        def _get_settings():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                settings = {}
                config = self._camera.get_config(self._context)
                self._walk_config(config, settings)
                return settings

        settings = await asyncio.get_event_loop().run_in_executor(None, _get_settings)
        self._settings_cache = settings

        logger.info("settings_discovered", count=len(settings))
        return settings

    async def get_common_settings(self) -> dict[str, CameraSetting]:
        """
        Get only the commonly used settings.

        Returns:
            Dictionary of common setting names to CameraSetting objects.
        """
        result = {}

        def _get_common():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                config = self._camera.get_config(self._context)

                for name, path in COMMON_SETTINGS.items():
                    try:
                        widget = config.get_child_by_name(path.split('/')[-1])
                        setting = self._widget_to_setting(widget, path)
                        if setting:
                            result[name] = setting
                    except gp.GPhoto2Error:
                        # Setting not available on this camera
                        pass

        await asyncio.get_event_loop().run_in_executor(None, _get_common)
        return result

    async def get_setting(self, name: str) -> CameraSetting:
        """
        Get a specific setting by name.

        Args:
            name: Setting name (e.g., "iso", "aperture")

        Returns:
            CameraSetting object.

        Raises:
            SettingNotFoundError: If setting doesn't exist.
        """
        def _get_setting():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                config = self._camera.get_config(self._context)

                # Try common settings path first
                if name in COMMON_SETTINGS:
                    path = COMMON_SETTINGS[name]
                    try:
                        widget = config.get_child_by_name(path.split('/')[-1])
                        setting = self._widget_to_setting(widget, path)
                        if setting:
                            return setting
                    except gp.GPhoto2Error:
                        pass

                # Try direct name lookup
                try:
                    widget = config.get_child_by_name(name)
                    return self._widget_to_setting(widget, f"/{name}")
                except gp.GPhoto2Error:
                    raise SettingNotFoundError(name)

        return await asyncio.get_event_loop().run_in_executor(None, _get_setting)

    async def set_setting(self, name: str, value: Any) -> CameraSetting:
        """
        Set a camera setting value.

        Args:
            name: Setting name
            value: New value to set

        Returns:
            Updated CameraSetting object.

        Raises:
            SettingNotFoundError: If setting doesn't exist.
            SettingReadOnlyError: If setting is read-only.
            SettingValueError: If value is invalid.
        """
        def _set_setting():
            with self._lock:
                if not self._camera:
                    raise CameraDisconnectedError()

                config = self._camera.get_config(self._context)

                # Find the widget
                widget = None
                if name in COMMON_SETTINGS:
                    path = COMMON_SETTINGS[name]
                    try:
                        widget = config.get_child_by_name(path.split('/')[-1])
                    except gp.GPhoto2Error:
                        pass

                if widget is None:
                    try:
                        widget = config.get_child_by_name(name)
                    except gp.GPhoto2Error:
                        raise SettingNotFoundError(name)

                # Check if read-only
                if widget.get_readonly():
                    raise SettingReadOnlyError(
                        name,
                        "Setting is read-only. Check camera mode dial (must be P/A/S/M)."
                    )

                # Validate value for radio/menu types
                widget_type = widget.get_type()
                if widget_type in (gp.GP_WIDGET_RADIO, gp.GP_WIDGET_MENU):
                    choices = []
                    for i in range(widget.count_choices()):
                        try:
                            choices.append(widget.get_choice(i))
                        except gp.GPhoto2Error:
                            break

                    if str(value) not in choices:
                        raise SettingValueError(name, str(value), choices)

                # Set the value
                try:
                    widget.set_value(str(value))
                    self._camera.set_config(config, self._context)
                except gp.GPhoto2Error as e:
                    raise SettingValueError(name, str(value))

                # Return updated setting
                # Re-fetch to confirm the change
                config = self._camera.get_config(self._context)
                try:
                    widget = config.get_child_by_name(name)
                except gp.GPhoto2Error:
                    if name in COMMON_SETTINGS:
                        path = COMMON_SETTINGS[name]
                        widget = config.get_child_by_name(path.split('/')[-1])

                return self._widget_to_setting(widget, COMMON_SETTINGS.get(name, f"/{name}"))

        result = await asyncio.get_event_loop().run_in_executor(None, _set_setting)

        # Clear cache after setting change
        self._settings_cache = None

        logger.info("setting_changed", name=name, value=value)
        return result

    async def get_battery_level(self) -> Optional[int]:
        """
        Get current battery level.

        Returns:
            Battery percentage (0-100) or None if not available.
        """
        try:
            setting = await self.get_setting("batterylevel")
            if setting.value:
                # Value might be "50%" or just "50"
                value = str(setting.value).replace("%", "").strip()
                return int(value)
        except (SettingNotFoundError, ValueError):
            pass
        return None

    def clear_cache(self) -> None:
        """Clear the settings cache."""
        self._settings_cache = None
