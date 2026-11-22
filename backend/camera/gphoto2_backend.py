"""python-gphoto2 implementation of CameraBackend.

The only module allowed to import gphoto2. Blocking; called from one worker thread.
Every ``gphoto2.GPhoto2Error`` is translated to a domain exception (gphoto2 code in details).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gphoto2 as gp
import structlog

from backend.camera.backend import (
    CameraEvent,
    CameraFileInfo,
    CameraFilePath,
    ConfigRange,
    ConfigType,
    ConfigWidget,
    EventType,
    FileKind,
    StorageInfo,
)
from backend.core.errors import (
    AppError,
    CameraBusy,
    CameraIOError,
    CameraNotConnected,
    CameraNotFound,
    CameraTimeout,
    FeatureUnsupported,
    FileNotFoundError_,
    SettingInvalid,
    SettingNotAllowed,
    SettingNotFound,
)

log = structlog.get_logger(__name__)

_CHUNK = 1024 * 1024

_IO_CODES = {
    gp.GP_ERROR_IO,
    gp.GP_ERROR_IO_INIT,
    gp.GP_ERROR_IO_LOCK,
    gp.GP_ERROR_IO_READ,
    gp.GP_ERROR_IO_WRITE,
    gp.GP_ERROR_IO_UPDATE,
    gp.GP_ERROR_IO_USB_CLEAR_HALT,
    gp.GP_ERROR_IO_USB_FIND,
    gp.GP_ERROR_IO_SUPPORTED_USB,
    gp.GP_ERROR_UNKNOWN_PORT,
}

_WIDGET_TYPES: dict[int, ConfigType] = {
    gp.GP_WIDGET_RADIO: ConfigType.RADIO,
    gp.GP_WIDGET_MENU: ConfigType.MENU,
    gp.GP_WIDGET_TEXT: ConfigType.TEXT,
    gp.GP_WIDGET_RANGE: ConfigType.RANGE,
    gp.GP_WIDGET_TOGGLE: ConfigType.TOGGLE,
    gp.GP_WIDGET_DATE: ConfigType.DATE,
    gp.GP_WIDGET_SECTION: ConfigType.SECTION,
    gp.GP_WIDGET_WINDOW: ConfigType.SECTION,
    gp.GP_WIDGET_BUTTON: ConfigType.BUTTON,
}

_FILE_TYPES = {
    FileKind.NORMAL: gp.GP_FILE_TYPE_NORMAL,
    FileKind.PREVIEW: gp.GP_FILE_TYPE_PREVIEW,
    FileKind.EXIF: gp.GP_FILE_TYPE_EXIF,
}


# --------------------------------------------------------------------------- errors


def gp_code(exc: BaseException) -> int | None:
    """gphoto2 error code of ``exc`` (GPhoto2Error.code), or None."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def translate_error(exc: BaseException, op: str) -> AppError:
    """Map a GPhoto2Error to the matching domain exception, keeping the gphoto2 code."""
    code = gp_code(exc)
    try:
        text = gp.gp_result_as_string(code) if code is not None else str(exc)
    except Exception:  # noqa: BLE001 - message lookup must never mask the real error
        text = str(exc)
    details: dict[str, Any] = {"gphoto2_code": code, "gphoto2_message": text, "operation": op}
    msg = f"{op}: {text}"
    if code == gp.GP_ERROR_MODEL_NOT_FOUND:
        return CameraNotFound(details=details)
    if code == gp.GP_ERROR_CAMERA_BUSY:
        return CameraBusy(msg, details=details)
    if code == gp.GP_ERROR_IO_USB_CLAIM:
        # Usually another process (gvfs/gphoto2 CLI) holds the device.
        return CameraBusy(f"{msg} (device claimed by another process?)", details=details)
    if code == gp.GP_ERROR_TIMEOUT:
        return CameraTimeout(msg, details=details)
    if code in (gp.GP_ERROR_FILE_NOT_FOUND, gp.GP_ERROR_DIRECTORY_NOT_FOUND):
        return FileNotFoundError_(msg, details=details)
    if code == gp.GP_ERROR_NOT_SUPPORTED:
        return FeatureUnsupported(msg, details=details)
    # IO/USB family, CAMERA_ERROR, NO_SPACE, corrupted data and anything unknown.
    return CameraIOError(msg, details=details)


# ------------------------------------------------------------------ widget conversion


def widget_to_config(widget: Any, parent_path: str = "") -> ConfigWidget:
    """Convert a gphoto2 widget (recursively for sections) into a ConfigWidget."""
    wtype = _WIDGET_TYPES.get(widget.get_type(), ConfigType.TEXT)
    name = widget.get_name()
    path = f"{parent_path}/{name}"
    base = {
        "name": name,
        "label": widget.get_label(),
        "path": path,
        "type": wtype,
        "readonly": bool(widget.get_readonly()),
    }
    if wtype is ConfigType.SECTION:
        kids = tuple(
            widget_to_config(widget.get_child(i), path) for i in range(widget.count_children())
        )
        return ConfigWidget(**base, children=kids)
    value: str | int | float | bool | None
    try:
        value = widget.get_value()
    except gp.GPhoto2Error:
        value = None  # buttons and some unreadable widgets have no value
    if wtype is ConfigType.TOGGLE:
        value = None if value == 2 or value is None else bool(value)  # 2 == undefined
    choices: tuple[str, ...] = ()
    if wtype in (ConfigType.RADIO, ConfigType.MENU):
        choices = tuple(widget.get_choice(i) for i in range(widget.count_choices()))
    rng: ConfigRange | None = None
    if wtype is ConfigType.RANGE:
        lo, hi, step = widget.get_range()
        rng = ConfigRange(min=float(lo), max=float(hi), step=float(step))
    return ConfigWidget(**base, value=value, choices=choices, range=rng)


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def coerce_config_value(w: ConfigWidget, value: object) -> str | int | float:
    """Validate/coerce ``value`` for widget ``w``; returns what to hand to widget.set_value."""
    if w.readonly:
        raise SettingNotAllowed(f"Setting '{w.name}' is read-only", details={"name": w.name})

    def bad(why: str) -> SettingInvalid:
        return SettingInvalid(
            f"Invalid value {value!r} for '{w.name}': {why}",
            details={"name": w.name, "value": value, "type": str(w.type)},
        )

    t = w.type
    if t in (ConfigType.RADIO, ConfigType.MENU):
        if isinstance(value, bool):
            raise bad("boolean not accepted")
        candidates = [str(value)]
        if isinstance(value, float) and value.is_integer():
            candidates.append(str(int(value)))
        for c in candidates:
            if c in w.choices:
                return c
        raise bad("not one of the available choices")
    if t is ConfigType.RANGE:
        if not _is_number(value):
            raise bad("number required")
        v = float(value)  # type: ignore[arg-type]
        r = w.range
        if r is None:
            return v
        if not (r.min <= v <= r.max):
            raise bad(f"must be within [{r.min}, {r.max}]")
        if r.step > 0:
            n = (v - r.min) / r.step
            if abs(n - round(n)) > 1e-6:
                raise bad(f"must be a multiple of {r.step} from {r.min}")
        return v
    if t is ConfigType.TOGGLE:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int) and value in (0, 1):
            return value
        raise bad("bool, 0 or 1 required")
    if t is ConfigType.DATE:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise bad("integer epoch seconds required")
    if t is ConfigType.TEXT:
        if isinstance(value, str):
            return value
        raise bad("string required")
    raise bad(f"widget of type {t} cannot be set")


# ------------------------------------------------------------------------- backend


class Gphoto2Backend:
    """CameraBackend over python-gphoto2."""

    def __init__(self) -> None:
        self._camera: Any = None
        self._ctx: Any = None
        self._model = ""
        self._viewfinder_on = False

    # -- lifecycle

    @property
    def is_open(self) -> bool:
        return self._camera is not None

    def open(self) -> None:
        if self._camera is not None:
            self.close()
        camera = gp.Camera()
        ctx = gp.Context()
        try:
            camera.init(ctx)
            model = camera.get_abilities().model
        except gp.GPhoto2Error as e:
            self._exit_quietly(camera, ctx)
            raise translate_error(e, "open") from e
        self._camera, self._ctx, self._model = camera, ctx, str(model)
        self._viewfinder_on = False

    def close(self) -> None:
        camera, ctx = self._camera, self._ctx
        self._camera = self._ctx = None
        self._viewfinder_on = False
        if camera is not None:
            self._exit_quietly(camera, ctx)

    @staticmethod
    def _exit_quietly(camera: Any, ctx: Any) -> None:
        try:
            camera.exit(ctx)
        except Exception as e:  # noqa: BLE001 - close must never raise (e.g. after USB loss)
            log.warning("gphoto2_exit_failed", error=str(e), code=gp_code(e))

    def _cam(self) -> Any:
        if self._camera is None:
            raise CameraNotConnected()
        return self._camera

    # -- info

    def summary(self) -> str:
        cam = self._cam()
        try:
            s = cam.get_summary(self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, "summary") from e
        return str(getattr(s, "text", None) or s)

    def model(self) -> str:
        self._cam()
        return self._model

    # -- config

    def list_config(self) -> list[ConfigWidget]:
        cam = self._cam()
        try:
            root = cam.get_config(self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, "list_config") from e
        top = widget_to_config(root)
        return list(top.children)

    def _lookup(self, name: str) -> tuple[Any, ConfigWidget]:
        """Return (raw widget, converted leaf) for ``name``."""
        cam = self._cam()
        widget: Any = None
        try:
            widget = cam.get_single_config(name, self._ctx)
        except gp.GPhoto2Error as e:
            if gp_code(e) not in (
                gp.GP_ERROR_BAD_PARAMETERS,
                gp.GP_ERROR_NOT_SUPPORTED,
                gp.GP_ERROR_DIRECTORY_NOT_FOUND,
            ):
                raise translate_error(e, f"get_config({name})") from e
        if widget is None:  # driver lacks get_single_config or name unknown: full tree
            try:
                root = cam.get_config(self._ctx)
                widget = root.get_child_by_name(name)
            except gp.GPhoto2Error as e:
                if gp_code(e) in (gp.GP_ERROR_BAD_PARAMETERS, gp.GP_ERROR_NOT_SUPPORTED, None):
                    raise SettingNotFound(
                        f"Setting '{name}' not found", details={"name": name}
                    ) from e
                raise translate_error(e, f"get_config({name})") from e
        try:
            return widget, widget_to_config(widget, self._parent_path(widget))
        except gp.GPhoto2Error as e:
            raise translate_error(e, f"get_config({name})") from e

    @staticmethod
    def _parent_path(widget: Any) -> str:
        parts: list[str] = []
        cur = widget
        while True:
            try:
                cur = cur.get_parent()
            except gp.GPhoto2Error:
                break
            if cur is None:
                break
            parts.append(cur.get_name())
        return "".join(f"/{p}" for p in reversed(parts))

    def get_config(self, name: str) -> ConfigWidget:
        return self._lookup(name)[1]

    def set_config(self, name: str, value: str | int | float | bool) -> None:
        raw, conv = self._lookup(name)
        coerced = coerce_config_value(conv, value)
        cam = self._cam()
        try:
            raw.set_value(coerced)
            try:
                cam.set_single_config(name, raw, self._ctx)
            except gp.GPhoto2Error as e:
                if gp_code(e) != gp.GP_ERROR_NOT_SUPPORTED:
                    raise
                # driver lacks set_single_config: push the full tree
                root = cam.get_config(self._ctx)
                root.get_child_by_name(name).set_value(coerced)
                cam.set_config(root, self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, f"set_config({name})") from e

    # -- capture

    def capture(self) -> CameraFilePath:
        cam = self._cam()
        try:
            p = cam.capture(gp.GP_CAPTURE_IMAGE, self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, "capture") from e
        return CameraFilePath(folder=p.folder, name=p.name)

    def trigger(self) -> None:
        cam = self._cam()
        try:
            cam.trigger_capture(self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, "trigger") from e

    def capture_preview(self) -> bytes:
        cam = self._cam()
        try:
            if not self._viewfinder_on:
                self._enable_viewfinder()
            f = cam.capture_preview(self._ctx)
            return bytes(f.get_data_and_size())
        except gp.GPhoto2Error as e:
            raise translate_error(e, "capture_preview") from e

    def _enable_viewfinder(self) -> None:
        # Best effort: not every body exposes "viewfinder"; preview may still work without it.
        try:
            self.set_config("viewfinder", 1)
        except (SettingNotFound, SettingNotAllowed, SettingInvalid, FeatureUnsupported) as e:
            log.info("viewfinder_not_set", reason=e.message)
        self._viewfinder_on = True

    def wait_for_event(self, timeout_s: float) -> CameraEvent:
        cam = self._cam()
        try:
            etype, data = cam.wait_for_event(max(0, int(timeout_s * 1000)), self._ctx)
        except gp.GPhoto2Error as e:
            if gp_code(e) == gp.GP_ERROR_TIMEOUT:
                return CameraEvent(EventType.TIMEOUT)
            raise translate_error(e, "wait_for_event") from e
        if etype == gp.GP_EVENT_TIMEOUT:
            return CameraEvent(EventType.TIMEOUT)
        if etype == gp.GP_EVENT_FILE_ADDED:
            return CameraEvent(EventType.FILE_ADDED, CameraFilePath(data.folder, data.name))
        if etype == gp.GP_EVENT_FOLDER_ADDED:
            return CameraEvent(
                EventType.FOLDER_ADDED, payload={"folder": data.folder, "name": data.name}
            )
        if etype == gp.GP_EVENT_CAPTURE_COMPLETE:
            return CameraEvent(EventType.CAPTURE_COMPLETE)
        return CameraEvent(EventType.UNKNOWN, payload={"gphoto2_type": etype, "data": str(data)})

    # -- filesystem

    def list_folders(self, folder: str) -> list[str]:
        cam = self._cam()
        try:
            return [str(n) for n, _ in cam.folder_list_folders(folder, self._ctx)]
        except gp.GPhoto2Error as e:
            raise translate_error(e, f"list_folders({folder})") from e

    def list_files(self, folder: str) -> list[CameraFileInfo]:
        cam = self._cam()
        out: list[CameraFileInfo] = []
        try:
            for name, _ in cam.folder_list_files(folder, self._ctx):
                f = cam.file_get_info(folder, name, self._ctx).file
                out.append(
                    CameraFileInfo(
                        folder=folder,
                        name=str(name),
                        size=int(f.size),
                        mtime=float(f.mtime),
                        mime_type=str(f.type),
                        width=int(f.width),
                        height=int(f.height),
                    )
                )
        except gp.GPhoto2Error as e:
            raise translate_error(e, f"list_files({folder})") from e
        return out

    def read_file(self, folder: str, name: str, kind: FileKind, dest: Path) -> None:
        cam = self._cam()
        ftype = _FILE_TYPES[kind]
        tmp = dest.with_name(dest.name + ".part")
        try:
            if kind is FileKind.NORMAL:
                self._read_chunked(cam, folder, name, ftype, tmp)
            else:  # previews/EXIF are small; let libgphoto2 build them
                cam.file_get(folder, name, ftype, self._ctx).save(str(tmp))
            tmp.replace(dest)
        except gp.GPhoto2Error as e:
            tmp.unlink(missing_ok=True)
            raise translate_error(e, f"read_file({folder}/{name})") from e
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read_chunked(self, cam: Any, folder: str, name: str, ftype: int, tmp: Path) -> None:
        size = int(cam.file_get_info(folder, name, self._ctx).file.size)
        buf = bytearray(min(_CHUNK, max(size, 1)))
        view = memoryview(buf)
        offset = 0
        with tmp.open("wb") as fh:
            while offset < size:
                want = min(len(buf), size - offset)
                n = int(cam.file_read(folder, name, ftype, offset, view[:want], self._ctx))
                if n <= 0:
                    raise CameraIOError(
                        f"Short read at offset {offset} of {size}",
                        details={"folder": folder, "name": name, "offset": offset},
                    )
                fh.write(view[:n])
                offset += n

    def delete_file(self, folder: str, name: str) -> None:
        cam = self._cam()
        try:
            cam.file_delete(folder, name, self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, f"delete_file({folder}/{name})") from e

    def storage_info(self) -> list[StorageInfo]:
        cam = self._cam()
        try:
            infos = cam.get_storageinfo(self._ctx)
        except gp.GPhoto2Error as e:
            raise translate_error(e, "storage_info") from e
        out: list[StorageInfo] = []
        for si in infos:
            fields = si.fields
            access = ""
            if fields & gp.GP_STORAGEINFO_ACCESS:
                access = "rw" if si.access == gp.GP_STORAGEINFO_AC_READWRITE else "ro"
            out.append(
                StorageInfo(
                    label=str(si.label) if fields & gp.GP_STORAGEINFO_LABEL else "",
                    base_dir=str(si.basedir) if fields & gp.GP_STORAGEINFO_BASE else "",
                    capacity_kb=int(si.capacitykbytes)
                    if fields & gp.GP_STORAGEINFO_MAXCAPACITY
                    else 0,
                    free_kb=int(si.freekbytes) if fields & gp.GP_STORAGEINFO_FREESPACEKBYTES else 0,
                    free_images=int(si.freeimages)
                    if fields & gp.GP_STORAGEINFO_FREESPACEIMAGES
                    else 0,
                    access=access,
                )
            )
        return out


__all__ = ["Gphoto2Backend", "coerce_config_value", "translate_error", "widget_to_config"]
