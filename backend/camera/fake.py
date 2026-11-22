"""In-memory fake camera modelled on a Nikon D500 as seen through gphoto2.

Implements the ``CameraBackend`` protocol with a virtual memory card, deterministic
tiny images and a thread-safe fault-injection API for tests and the "Demo camera".
Blocking and synchronous like the real backend; imports neither gphoto2 nor pytest.

Fault-injection ops are the backend method names: open, summary, model, list_config,
get_config, set_config, capture, trigger, capture_preview, wait_for_event,
list_folders, list_files, read_file, delete_file, storage_info (close never fails).
"""

from __future__ import annotations

import io
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

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
    CameraIOError,
    CameraNotConnected,
    CameraNotFound,
    FileNotFoundError_,
    SettingInvalid,
    SettingNotAllowed,
    SettingNotFound,
    StorageFull,
)

OPS = frozenset(
    {
        "open",
        "summary",
        "model",
        "list_config",
        "get_config",
        "set_config",
        "capture",
        "trigger",
        "capture_preview",
        "wait_for_event",
        "list_folders",
        "list_files",
        "read_file",
        "delete_file",
        "storage_info",
    }
)

CARD_BASE = "/store_00010001"
CARD_FOLDER = f"{CARD_BASE}/DCIM/100ND500"
_FOLDERS = {
    "/": ["store_00010001"],
    CARD_BASE: ["DCIM"],
    f"{CARD_BASE}/DCIM": ["100ND500"],
    CARD_FOLDER: [],
}
_IMG_SIZE = (320, 213)
_BASE_TIME = 1_700_000_000.0


def _fmt_comp(thirds: int) -> str:
    v = thirds / 3
    if thirds == 0:
        return "0"
    s = f"{abs(v):.1f}".rstrip("0").rstrip(".")
    return ("+" if v > 0 else "-") + s


_SHUTTER = [
    "30", "20", "15", "10", "8", "6", "4", "2.5", "2", "1.6", "1", "0.8", "0.5", "0.4", "0.3",
    "1/4", "1/5", "1/6", "1/8", "1/10", "1/15", "1/20", "1/30", "1/60", "1/125", "1/250",
    "1/500", "1/1000", "1/2000", "1/4000", "1/8000", "Bulb",
]  # fmt: skip


@dataclass
class _Spec:
    section: str
    name: str
    label: str
    type: ConfigType
    value: str | int | float | bool
    readonly: bool = False
    choices: tuple[str, ...] = ()
    range: ConfigRange | None = None


def _specs() -> list[_Spec]:
    R, T = ConfigType.RADIO, ConfigType.TOGGLE
    return [
        _Spec("actions", "viewfinder", "Viewfinder", T, False),
        _Spec("actions", "autofocusdrive", "Drive Nikon DSLR Autofocus", T, False),
        _Spec(
            "actions",
            "manualfocusdrive",
            "Drive Nikon DSLR Manual focus",
            ConfigType.RANGE,
            0.0,
            range=ConfigRange(-1000, 1000, 1),
        ),  # fmt: skip
        _Spec("actions", "movie", "Record a movie", T, False),
        _Spec("settings", "datetime", "Camera Date and Time", ConfigType.DATE, int(_BASE_TIME)),
        _Spec(
            "settings",
            "capturetarget",
            "Capture Target",
            R,
            "Memory card",
            choices=("Internal RAM", "Memory card"),
        ),  # fmt: skip
        _Spec("status", "serialnumber", "Serial Number", ConfigType.TEXT, "9000001", True),
        _Spec("status", "cameramodel", "Camera Model", ConfigType.TEXT, "D500", True),
        _Spec("status", "batterylevel", "Battery Level", ConfigType.TEXT, "87%", True),
        _Spec(
            "imgsettings",
            "iso",
            "ISO Speed",
            R,
            "100",
            choices=tuple(
                str(v)
                for v in (
                    100,
                    125,
                    160,
                    200,
                    250,
                    320,
                    400,
                    500,
                    640,
                    800,
                    1000,
                    1250,
                    1600,
                    2000,
                    2500,
                    3200,
                    6400,
                    12800,
                )
            ),
        ),  # fmt: skip
        _Spec(
            "imgsettings",
            "whitebalance",
            "White Balance",
            R,
            "Automatic",
            choices=(
                "Automatic",
                "Daylight",
                "Fluorescent",
                "Tungsten",
                "Flash",
                "Cloudy",
                "Shade",
                "Preset",
            ),
        ),  # fmt: skip
        _Spec(
            "imgsettings",
            "imagequality",
            "Image Quality",
            R,
            "JPEG Fine",
            choices=(
                "JPEG Basic",
                "JPEG Normal",
                "JPEG Fine",
                "NEF (Raw)",
                "NEF+JPEG Basic",
                "NEF+JPEG Normal",
                "NEF+JPEG Fine",
            ),
        ),  # fmt: skip
        _Spec(
            "imgsettings",
            "imagesize",
            "Image Size",
            R,
            "5568x3712",
            choices=("5568x3712", "4176x2784", "2784x1856"),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "f-number",
            "Fixed Aperture",
            R,
            "f/5.6",
            choices=tuple(f"f/{v}" for v in ("1.4", "2", "2.8", "4", "5.6", "8", "11", "16", "22")),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "shutterspeed",
            "Shutter Speed",
            R,
            "1/250",
            choices=tuple(_SHUTTER),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "exposurecompensation",
            "Exposure Compensation",
            R,
            "0",
            choices=tuple(_fmt_comp(i) for i in range(-15, 16)),
        ),  # fmt: skip
        _Spec("capturesettings", "expprogram", "Exposure Program", ConfigType.TEXT, "M", True),
        _Spec(
            "capturesettings",
            "autoexposuremode",
            "Auto Exposure Mode",
            R,
            "Manual",
            choices=("Manual", "Aperture Priority", "Shutter Priority", "Program"),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "focusmode",
            "Focus Mode",
            R,
            "AF-S",
            choices=("AF-S", "AF-C", "AF-A", "Manual"),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "meteringmode",
            "Metering Mode",
            R,
            "Matrix",
            choices=("Matrix", "Center Weighted", "Spot"),
        ),  # fmt: skip
        _Spec(
            "capturesettings",
            "liveviewsize",
            "Live View Size",
            R,
            "Large",
            choices=("Small", "Medium", "Large"),
        ),  # fmt: skip
        _Spec("capturesettings", "bulb", "Bulb Capture", T, False),
    ]


_SECTION_LABELS = {
    "actions": "Camera Actions",
    "settings": "Camera Settings",
    "status": "Camera Status Information",
    "imgsettings": "Image Settings",
    "capturesettings": "Capture Settings",
}


@dataclass
class _File:
    data: bytes
    preview: bytes
    mtime: float
    mime: str
    width: int = 0
    height: int = 0


@dataclass
class _Faults:
    fail: dict[str, deque[Exception]] = field(default_factory=dict)
    hangs: dict[str, threading.Event] = field(default_factory=dict)
    latency: dict[str, float] = field(default_factory=dict)
    unplugged: bool = False
    card_full: bool = False
    calls: dict[str, int] = field(default_factory=dict)


def _jpeg(lines: list[str], rng: random.Random) -> bytes:
    img = Image.new("RGB", _IMG_SIZE, (rng.randrange(40, 120), rng.randrange(40, 120), 90))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((8, 8 + 14 * i), line, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def _nef(jpeg: bytes) -> bytes:
    """TIFF container with JPEG-compressed image data (stand-in for a NEF)."""
    with Image.open(io.BytesIO(jpeg)) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "TIFF", compression="jpeg")
    return buf.getvalue()


class FakeCamera:
    """Fake ``CameraBackend``. Fault-injection methods may be called from any thread."""

    def __init__(
        self,
        *,
        seed: int = 0,
        start_counter: int = 1,
        capacity_kb: int = 8192,
        emit_capture_complete: bool = False,
    ) -> None:
        """``emit_capture_complete``: queue a CAPTURE_COMPLETE event after each capture.
        Default False mirrors real PTP bodies, where capture() usually consumes it."""
        self._emit_complete = emit_capture_complete
        self._rng = random.Random(seed)  # noqa: S311
        self._specs = {s.name: s for s in _specs()}
        self._values: dict[str, str | int | float | bool] = {
            n: s.value for n, s in self._specs.items()
        }
        self._open = False
        self._counter = start_counter
        self._capacity_kb = capacity_kb
        self._clock = 0
        self._preview_n = 0
        self._files: dict[str, dict[str, _File]] = {CARD_FOLDER: {}}
        self._events: deque[CameraEvent] = deque()
        self._cond = threading.Condition()
        self._flock = threading.Lock()
        self._faults = _Faults()

    # ---- fault injection (thread-safe) ----

    @property
    def calls(self) -> dict[str, int]:
        """Snapshot of per-op call counters (every attempted call, including failed ones)."""
        with self._flock:
            return dict(self._faults.calls)

    def _check_op(self, op: str) -> None:
        if op not in OPS:
            raise ValueError(f"unknown op {op!r}; expected one of {sorted(OPS)}")

    def fail_next(self, op: str, n: int = 1, exc: Exception | None = None) -> None:
        """Make the next ``n`` calls of ``op`` raise ``exc`` (default CameraIOError)."""
        self._check_op(op)
        with self._flock:
            q = self._faults.fail.setdefault(op, deque())
            q.extend(
                exc if exc is not None else CameraIOError("Injected failure") for _ in range(n)
            )

    def hang(self, op: str) -> threading.Event:
        """Block every call of ``op`` until the returned event is set or ``release_all()``."""
        self._check_op(op)
        with self._flock:
            ev = self._faults.hangs.get(op)
            if ev is None or ev.is_set():
                ev = self._faults.hangs[op] = threading.Event()
            return ev

    def release_all(self) -> None:
        """Release every hung call and clear all hangs."""
        with self._flock:
            events = list(self._faults.hangs.values())
            self._faults.hangs.clear()
        for ev in events:
            ev.set()

    def unplug(self) -> None:
        """Every op raises CameraIOError (open raises CameraNotFound) until ``replug()``."""
        with self._flock:
            self._faults.unplugged = True

    def replug(self) -> None:
        with self._flock:
            self._faults.unplugged = False

    def set_latency(self, op: str, seconds: float) -> None:
        """Sleep ``seconds`` at the start of each ``op`` call (0 clears)."""
        self._check_op(op)
        with self._flock:
            self._faults.latency[op] = seconds

    def card_full(self, full: bool = True) -> None:
        """While set, capture/trigger/movie raise CameraIOError and free space reads 0."""
        with self._flock:
            self._faults.card_full = full

    def _enter(self, op: str) -> None:
        with self._flock:
            f = self._faults
            f.calls[op] = f.calls.get(op, 0) + 1
            hang = f.hangs.get(op)
            latency = f.latency.get(op, 0.0)
        if hang is not None:
            hang.wait()
        if latency > 0:
            time.sleep(latency)
        with self._flock:
            f = self._faults
            if f.unplugged:
                if op == "open":
                    raise CameraNotFound()
                raise CameraIOError("Camera unplugged")
            q = f.fail.get(op)
            if q:
                raise q.popleft()
        if op != "open" and not self._open:
            raise CameraNotConnected()

    # ---- lifecycle ----

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._enter("open")
        self._open = True

    def close(self) -> None:
        self._open = False

    def summary(self) -> str:
        self._enter("summary")
        return f"Manufacturer: Nikon Corporation\nModel: {self.cameramodel}\nFake camera"

    @property
    def cameramodel(self) -> str:
        return "Nikon DSC D500"

    def model(self) -> str:
        self._enter("model")
        return self.cameramodel

    # ---- config ----

    def _widget(self, s: _Spec) -> ConfigWidget:
        return ConfigWidget(
            name=s.name,
            label=s.label,
            path=f"/main/{s.section}/{s.name}",
            type=s.type,
            value=self._values[s.name],
            readonly=s.readonly,
            choices=s.choices,
            range=s.range,
        )

    def list_config(self) -> list[ConfigWidget]:
        self._enter("list_config")
        out = []
        for sec, label in _SECTION_LABELS.items():
            kids = tuple(self._widget(s) for s in self._specs.values() if s.section == sec)
            out.append(
                ConfigWidget(
                    name=sec,
                    label=label,
                    path=f"/main/{sec}",
                    type=ConfigType.SECTION,
                    children=kids,
                )  # fmt: skip
            )
        return out

    def get_config(self, name: str) -> ConfigWidget:
        self._enter("get_config")
        return self._widget(self._spec(name))

    def _spec(self, name: str) -> _Spec:
        try:
            return self._specs[name]
        except KeyError:
            raise SettingNotFound(f"Setting {name!r} not found") from None

    def set_config(self, name: str, value: str | int | float | bool) -> None:
        self._enter("set_config")
        s = self._spec(name)
        if s.readonly:
            raise SettingNotAllowed(f"Setting {name!r} is read-only")
        new = self._coerce(s, value)
        old = self._values[name]
        if name in ("movie", "bulb") and old and not new:
            self._check_space()
            if name == "bulb":
                self._do_capture()
            else:
                n = self._next_name()
                mov = b"\x00\x00\x00\x14ftypqt  fake movie"
                self._add_file(
                    f"DSC_{n:04d}.MOV",
                    _File(
                        mov,
                        _jpeg([f"DSC_{n:04d}.MOV"], self._rng),
                        self._stamp(),
                        "video/quicktime",
                    ),
                )
        self._values[name] = new

    @staticmethod
    def _coerce(s: _Spec, value: object) -> str | int | float | bool:
        """Same accept/reject rules as ``gphoto2_backend.coerce_config_value``."""

        def bad(why: str) -> SettingInvalid:
            return SettingInvalid(
                f"Invalid value {value!r} for {s.name!r}: {why}",
                details={"name": s.name, "value": value, "type": str(s.type)},
            )

        is_num = isinstance(value, int | float) and not isinstance(value, bool)
        t = s.type
        if t is ConfigType.RADIO or t is ConfigType.MENU:
            if isinstance(value, bool):
                raise bad("boolean not accepted")
            candidates = [str(value)]
            if isinstance(value, float) and value.is_integer():
                candidates.append(str(int(value)))
            for c in candidates:
                if c in s.choices:
                    return c
            raise bad("not one of the available choices")
        if t is ConfigType.RANGE:
            if not is_num:
                raise bad("number required")
            v = float(value)  # type: ignore[arg-type]
            r = s.range
            if r is None:
                return v
            if not r.min <= v <= r.max:
                raise bad(f"must be within [{r.min}, {r.max}]")
            if r.step > 0:
                n = (v - r.min) / r.step
                if abs(n - round(n)) > 1e-6:
                    raise bad(f"must be a multiple of {r.step} from {r.min}")
            return v
        if t is ConfigType.TOGGLE:
            if isinstance(value, bool):
                return value
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
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

    # ---- capture ----

    def _next_name(self) -> int:
        n = self._counter
        self._counter = n % 9999 + 1
        return n

    def _used_kb(self) -> int:
        return sum(len(f.data) for fs in self._files.values() for f in fs.values()) // 1024

    def _free_kb(self) -> int:
        if self._faults.card_full:
            return 0
        return max(0, self._capacity_kb - self._used_kb())

    def _add_file(self, name: str, f: _File) -> CameraFilePath:
        self._files[CARD_FOLDER][name] = f
        path = CameraFilePath(CARD_FOLDER, name)
        with self._cond:
            self._events.append(CameraEvent(EventType.FILE_ADDED, file=path))
            self._cond.notify_all()
        return path

    def _stamp(self) -> float:
        self._clock += 1
        return _BASE_TIME + self._clock

    def _check_space(self) -> None:
        with self._flock:
            full = self._faults.card_full
        if full or self._free_kb() <= 0:
            raise StorageFull("Card full")

    def _do_capture(self) -> CameraFilePath:
        self._check_space()
        n = self._next_name()
        v = self._values
        quality = str(v["imagequality"])
        lines = [
            f"DSC_{n:04d}",
            f"ISO {v['iso']}  {v['f-number']}  {v['shutterspeed']}s",
        ]
        jpg = _jpeg(lines, self._rng)
        w, h = _IMG_SIZE
        made: list[CameraFilePath] = []
        if quality.startswith("NEF"):
            made.append(
                self._add_file(
                    f"DSC_{n:04d}.NEF",
                    _File(_nef(jpg), jpg, self._stamp(), "image/x-nikon-nef", w, h),
                )
            )
        if not quality.startswith("NEF") or "+" in quality:
            made.append(
                self._add_file(
                    f"DSC_{n:04d}.JPG", _File(jpg, jpg, self._stamp(), "image/jpeg", w, h)
                )
            )
        if self._emit_complete:
            with self._cond:
                self._events.append(CameraEvent(EventType.CAPTURE_COMPLETE))
                self._cond.notify_all()
        return made[0]

    def capture(self) -> CameraFilePath:
        self._enter("capture")
        return self._do_capture()

    def trigger(self) -> None:
        self._enter("trigger")
        self._do_capture()

    def capture_preview(self) -> bytes:
        self._enter("capture_preview")
        self._values["viewfinder"] = True  # real D500 auto-starts live view
        self._preview_n += 1
        return _jpeg([f"LIVE {self._preview_n}"], self._rng)

    def wait_for_event(self, timeout_s: float) -> CameraEvent:
        self._enter("wait_for_event")
        with self._cond:
            if not self._events:
                self._cond.wait_for(lambda: bool(self._events), timeout=max(0.0, timeout_s))
            if self._events:
                return self._events.popleft()
        return CameraEvent(EventType.TIMEOUT)

    # ---- files ----

    def list_folders(self, folder: str) -> list[str]:
        self._enter("list_folders")
        key = folder.rstrip("/") or "/"
        if key not in _FOLDERS:
            raise FileNotFoundError_(f"Folder {folder!r} not found")
        return list(_FOLDERS[key])

    def _folder(self, folder: str) -> dict[str, _File]:
        key = folder.rstrip("/") or "/"
        if key not in self._files:
            raise FileNotFoundError_(f"Folder {folder!r} not found")
        return self._files[key]

    def list_files(self, folder: str) -> list[CameraFileInfo]:
        self._enter("list_files")
        key = folder.rstrip("/") or "/"
        if key not in _FOLDERS:
            raise FileNotFoundError_(f"Folder {folder!r} not found")
        return [
            CameraFileInfo(key, n, len(f.data), f.mtime, f.mime, f.width, f.height)
            for n, f in sorted(self._files.get(key, {}).items())
        ]

    def _get_file(self, folder: str, name: str) -> _File:
        try:
            return self._folder(folder)[name]
        except KeyError:
            raise FileNotFoundError_(f"File {folder}/{name} not found") from None

    def read_file(self, folder: str, name: str, kind: FileKind, dest: Path) -> None:
        self._enter("read_file")
        f = self._get_file(folder, name)
        dest.write_bytes(f.data if kind is FileKind.NORMAL else f.preview)

    def delete_file(self, folder: str, name: str) -> None:
        self._enter("delete_file")
        self._get_file(folder, name)
        del self._folder(folder)[name]

    def storage_info(self) -> list[StorageInfo]:
        self._enter("storage_info")
        files = [f for fs in self._files.values() for f in fs.values()]
        avg_kb = max(1, (sum(len(f.data) for f in files) // max(1, len(files))) // 1024)
        free = self._free_kb()
        return [
            StorageInfo(
                label="Memory card",
                base_dir=CARD_BASE,
                capacity_kb=self._capacity_kb,
                free_kb=free,
                free_images=free // avg_kb,
                access="rw",
            )  # fmt: skip
        ]
