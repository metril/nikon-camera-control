"""Safe, non-destructive smoke tests against a real Nikon D500 over USB.

Run (one camera, one process; the repo default is ``-n auto`` so override it):

    .venv/bin/pytest -m hardware --real-camera -n 0 -s tests/hardware

Without ``--real-camera`` every test here is skipped (see tests/conftest.py). ``-s`` shows the
printed measurements, which are the point: compare them with docs/HARDWARE_CHECKLIST.md.
The only camera-side effect is ONE test exposure on the card (test_capture_event_drain).
Nothing here writes settings, changes the clock, records video or deletes files.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from backend.camera.backend import ConfigType, ConfigWidget
from backend.camera.gphoto2_backend import Gphoto2Backend
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import SettingNotFound
from backend.core.events import EventBus

pytestmark = pytest.mark.hardware

# Widgets the app drives. REQUIRED ones fail the test when absent; the rest are reported.
REQUIRED = ("iso", "f-number", "shutterspeed", "imagequality", "viewfinder")
OPTIONAL = (
    "exposurecompensation",
    "autoexposuremode",
    "focusmode",
    "whitebalance",
    "imagesize",
    "liveviewsize",
    "capturetarget",
    "meteringmode",
    "batterylevel",
    "datetime",
    "bulb",
    "movie",
    "manualfocusdrive",
    "autofocusdrive",
)
KEY_CHOICE_SETTINGS = (
    "iso",
    "f-number",
    "shutterspeed",
    "exposurecompensation",
    "whitebalance",
    "imagequality",
)


@pytest.fixture(autouse=True)
def _single_process(request: pytest.FixtureRequest) -> None:
    n = getattr(request.config.option, "numprocesses", 0)
    if n:
        pytest.fail("one camera, one process: run with -n 0")


@pytest.fixture
def backend() -> object:
    b = Gphoto2Backend()
    b.open()
    try:
        yield b
    finally:
        b.close()


def _flatten(widgets: list[ConfigWidget] | tuple[ConfigWidget, ...]) -> dict[str, ConfigWidget]:
    out: dict[str, ConfigWidget] = {}
    for w in widgets:
        if w.type is ConfigType.SECTION:
            out.update(_flatten(w.children))
        else:
            out[w.name] = w
    return out


def test_open_and_model(backend: Gphoto2Backend) -> None:
    assert backend.is_open
    model = backend.model()
    print(f"\nmodel: {model!r}")
    assert "D500" in model.upper(), "this suite targets a Nikon D500"
    print(backend.summary()[:400])


def test_config_widgets_present(backend: Gphoto2Backend) -> None:
    flat = _flatten(backend.list_config())
    print(f"\n{len(flat)} leaf widgets")
    missing = [n for n in (*REQUIRED, *OPTIONAL) if n not in flat]
    print("missing widgets (app features that will be unavailable):", missing or "none")
    for n in (*REQUIRED, *OPTIONAL):
        if n in flat:
            w = flat[n]
            print(f"  {w.path:<40} {w.type.value:<7} ro={w.readonly} value={w.value!r}")
    assert not [n for n in REQUIRED if n not in flat], "required widgets missing"


def test_single_config_read(backend: Gphoto2Backend) -> None:
    w = backend.get_config("iso")
    print(f"\niso path={w.path} type={w.type.value} value={w.value!r}")
    assert w.name == "iso" and w.path.endswith("/iso")
    with pytest.raises(SettingNotFound):
        backend.get_config("definitely-not-a-widget")


def test_key_setting_choices(backend: Gphoto2Backend) -> None:
    """Prints the raw choice strings so the app's tolerant matching can be compared."""
    for name in KEY_CHOICE_SETTINGS:
        try:
            w = backend.get_config(name)
        except SettingNotFound:
            print(f"\n{name}: NOT PRESENT")
            continue
        print(f"\n{name}: current={w.value!r} choices({len(w.choices)})={list(w.choices)}")


def test_storage_info(backend: Gphoto2Backend) -> None:
    t0 = time.monotonic()
    storage = backend.storage_info()
    print(f"\nstorage_info took {time.monotonic() - t0:.2f}s: {storage}")
    assert storage, "no storage reported (card inserted?)"


async def test_capture_event_drain(tmp_path: Path) -> None:
    """ONE exposure through CameraService; prints how long the event drain takes and which
    files arrive (JPEG, NEF, or both). Needs a card or capturetarget=RAM-friendly setup."""
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    store = ConfigStore(tmp_path / "config.json")
    svc = CameraService(Gphoto2Backend, store, bus)
    await svc.start()
    try:
        await svc.connect()
        t0 = time.monotonic()
        files = await svc.capture()
        dt = time.monotonic() - t0
        quiet = store.config.camera.event_quiet_window_s
        print(f"\ncapture + drain: {dt:.2f}s (quiet window {quiet}s); files={files}")
        assert files, "capture returned no files"
    finally:
        await svc.stop()
        bus.close()


def test_preview_frame_and_viewfinder_off(backend: Gphoto2Backend) -> None:
    t0 = time.monotonic()
    frame = backend.capture_preview()
    first = time.monotonic() - t0
    t1 = time.monotonic()
    n = 5
    for _ in range(n):
        backend.capture_preview()
    fps = n / (time.monotonic() - t1)
    print(f"\npreview: {len(frame)} bytes, first frame {first:.2f}s, ~{fps:.1f} fps")
    try:
        from io import BytesIO

        from PIL import Image

        print("frame size:", Image.open(BytesIO(frame)).size)
    except Exception as exc:  # noqa: BLE001 - informational only
        print("could not decode frame:", exc)
    assert frame[:2] == b"\xff\xd8", "not a JPEG"
    backend.end_preview()
    vf = backend.get_config("viewfinder")
    print("viewfinder after end_preview:", vf.value)
    assert str(vf.value) in ("0", "False", "false", "off"), "viewfinder still on"
