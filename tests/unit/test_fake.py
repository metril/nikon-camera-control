from __future__ import annotations

import io
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from backend.camera.backend import CameraBackend, ConfigType, EventType, FileKind
from backend.camera.fake import CARD_FOLDER, FakeCamera
from backend.core.errors import (
    CameraIOError,
    CameraNotConnected,
    CameraNotFound,
    CameraOperationFailed,
    CameraTimeout,
    FileNotFoundError_,
    SettingInvalid,
    SettingNotAllowed,
    SettingNotFound,
    StorageFull,
)


@pytest.fixture
def cam() -> FakeCamera:
    c = FakeCamera()
    c.open()
    return c


def drain(cam: FakeCamera) -> list:
    out = []
    while (e := cam.wait_for_event(0)).type is not EventType.TIMEOUT:
        out.append(e)
    return out


def test_protocol_and_lifecycle() -> None:
    c = FakeCamera()
    assert isinstance(c, CameraBackend)
    assert not c.is_open
    with pytest.raises(CameraNotConnected):
        c.summary()
    c.open()
    assert c.is_open and "D500" in c.model() and c.summary()
    c.close()
    c.close()
    assert not c.is_open


def test_config_tree_names(cam: FakeCamera) -> None:
    leaves = {k.name: k for s in cam.list_config() for k in s.children}
    for n in ("iso", "f-number", "shutterspeed", "exposurecompensation", "whitebalance",
              "imagequality", "focusmode", "expprogram", "capturetarget", "batterylevel",
              "datetime", "viewfinder", "autofocusdrive", "manualfocusdrive", "bulb", "movie",
              "liveviewsize", "serialnumber", "cameramodel", "autoexposuremode", "imagesize",
              "meteringmode"):  # fmt: skip
        assert n in leaves
    assert "Bulb" in leaves["shutterspeed"].choices and "1/250" in leaves["shutterspeed"].choices
    assert leaves["batterylevel"].value == "87%" and leaves["batterylevel"].readonly
    assert leaves["datetime"].type is ConfigType.DATE
    assert leaves["manualfocusdrive"].range is not None
    assert cam.get_config("iso").path == "/main/imgsettings/iso"


@pytest.mark.parametrize("bad", ["1", "true", "on", "0", "off", 2, -1, 1.0, None])
def test_toggle_rejects_what_real_backend_rejects(cam: FakeCamera, bad: object) -> None:
    with pytest.raises(SettingInvalid):
        cam.set_config("viewfinder", bad)  # type: ignore[arg-type]
    assert cam.get_config("viewfinder").value is False


def test_coercion_matches_real_rules(cam: FakeCamera) -> None:
    cam.set_config("viewfinder", True)
    cam.set_config("viewfinder", 0)
    cam.set_config("iso", 400.0)  # integral float -> "400"
    assert cam.get_config("iso").value == "400"
    for name, bad in [
        ("iso", True),  # bool not accepted for radio
        ("iso", 400.5),
        ("manualfocusdrive", "10"),  # numbers only, no strings
        ("manualfocusdrive", True),
        ("datetime", "1700000000"),
        ("datetime", 1.5),
        ("datetime", True),
    ]:
        with pytest.raises(SettingInvalid):
            cam.set_config(name, bad)  # type: ignore[arg-type]
    cam.set_config("datetime", 1_700_000_100.0)
    assert cam.get_config("datetime").value == 1_700_000_100
    assert cam.get_config("manualfocusdrive").value == 0.0


def test_config_set_and_validation(cam: FakeCamera) -> None:
    cam.set_config("iso", 400)
    assert cam.get_config("iso").value == "400"
    cam.set_config("viewfinder", 1)
    assert cam.get_config("viewfinder").value is True
    cam.set_config("manualfocusdrive", 10)
    with pytest.raises(SettingInvalid):
        cam.set_config("iso", "123")
    with pytest.raises(SettingInvalid):
        cam.set_config("manualfocusdrive", 99999)
    with pytest.raises(SettingInvalid):
        cam.set_config("viewfinder", "maybe")
    with pytest.raises(SettingNotAllowed):
        cam.set_config("batterylevel", "1%")
    with pytest.raises(SettingNotFound):
        cam.set_config("nope", 1)
    with pytest.raises(SettingNotFound):
        cam.get_config("nope")


@pytest.mark.parametrize("emit", [False, True])
@pytest.mark.parametrize(
    ("quality", "exts"),
    [("JPEG Fine", [".JPG"]), ("NEF (Raw)", [".NEF"]), ("NEF+JPEG Fine", [".NEF", ".JPG"])],
)
def test_capture_events_per_quality(quality: str, exts: list[str], emit: bool) -> None:
    cam = FakeCamera(emit_capture_complete=emit)
    cam.open()
    cam.set_config("imagequality", quality)
    first = cam.capture()
    assert first.folder == CARD_FOLDER and first.name.startswith("DSC_0001")
    events = drain(cam)
    types = [e.type for e in events]
    done = [EventType.CAPTURE_COMPLETE] if emit else []
    assert types == [EventType.FILE_ADDED] * len(exts) + done
    assert sorted(e.file.name[-4:] for e in events if e.file) == sorted(exts)
    assert sorted(f.name[-4:] for f in cam.list_files(CARD_FOLDER)) == sorted(exts)


def test_wait_timeout_and_trigger() -> None:
    cam = FakeCamera(emit_capture_complete=True)
    cam.open()
    assert cam.wait_for_event(0.01).type is EventType.TIMEOUT
    cam.trigger()
    assert cam.wait_for_event(0.5).type is EventType.FILE_ADDED
    assert cam.wait_for_event(0.5).type is EventType.CAPTURE_COMPLETE


def test_capture_complete_off_by_default(cam: FakeCamera) -> None:
    cam.trigger()
    assert [e.type for e in drain(cam)] == [EventType.FILE_ADDED]


def test_counter_wraps() -> None:
    c = FakeCamera(start_counter=9999)
    c.open()
    assert c.capture().name == "DSC_9999.JPG"
    assert c.capture().name == "DSC_0001.JPG"


def test_read_files_and_preview(cam: FakeCamera, tmp_path: Path) -> None:
    cam.set_config("imagequality", "NEF+JPEG Fine")
    cam.capture()
    jpg, nef, prev = tmp_path / "a.jpg", tmp_path / "a.nef", tmp_path / "p.jpg"
    cam.read_file(CARD_FOLDER, "DSC_0001.JPG", FileKind.NORMAL, jpg)
    cam.read_file(CARD_FOLDER, "DSC_0001.NEF", FileKind.NORMAL, nef)
    cam.read_file(CARD_FOLDER, "DSC_0001.NEF", FileKind.PREVIEW, prev)
    with Image.open(jpg) as im:
        assert im.format == "JPEG" and im.size == (320, 213)
    with Image.open(nef) as im:
        assert im.format == "TIFF"
        im.load()
    with Image.open(prev) as im:
        assert im.format == "JPEG"
    info = {f.name: f for f in cam.list_files(CARD_FOLDER)}
    assert info["DSC_0001.JPG"].size == jpg.stat().st_size
    assert info["DSC_0001.JPG"].mime_type == "image/jpeg"


def test_capture_deterministic() -> None:
    def shot() -> bytes:
        c = FakeCamera(seed=3)
        c.open()
        c.capture()
        return c._files[CARD_FOLDER]["DSC_0001.JPG"].data

    assert shot() == shot()


def test_preview_frames(cam: FakeCamera) -> None:
    a, b = cam.capture_preview(), cam.capture_preview()
    assert a != b
    assert Image.open(io.BytesIO(a)).format == "JPEG"
    assert cam.get_config("viewfinder").value is True


def test_movie_and_bulb(cam: FakeCamera) -> None:
    cam.set_config("movie", True)
    assert cam.list_files(CARD_FOLDER) == []
    cam.set_config("movie", False)
    assert [f.name for f in cam.list_files(CARD_FOLDER)] == ["DSC_0001.MOV"]
    assert [e.type for e in drain(cam)] == [EventType.FILE_ADDED]
    cam.set_config("bulb", True)
    cam.set_config("bulb", False)
    assert [e.type for e in drain(cam)] == [EventType.FILE_ADDED]


def test_folders_delete_storage(cam: FakeCamera, tmp_path: Path) -> None:
    assert cam.list_folders("/") == ["store_00010001"]
    assert cam.list_folders("/store_00010001/DCIM") == ["100ND500"]
    with pytest.raises(FileNotFoundError_):
        cam.list_files("/nope")
    before = cam.storage_info()[0]
    for _ in range(3):
        cam.capture()
    after = cam.storage_info()[0]
    assert after.capacity_kb == before.capacity_kb and after.free_kb <= before.free_kb
    p = cam.capture()
    cam.delete_file(p.folder, p.name)
    assert p.name not in [f.name for f in cam.list_files(p.folder)]
    with pytest.raises(FileNotFoundError_):
        cam.delete_file(p.folder, p.name)
    with pytest.raises(FileNotFoundError_):
        cam.read_file(p.folder, p.name, FileKind.NORMAL, tmp_path / "x")


def test_free_space_shrinks() -> None:
    c = FakeCamera(capacity_kb=20)
    c.open()
    free0 = c.storage_info()[0].free_kb
    c.capture()
    assert c.storage_info()[0].free_kb < free0


def test_fail_next(cam: FakeCamera) -> None:
    cam.fail_next("get_config", 2)
    for _ in range(2):
        with pytest.raises(CameraIOError):
            cam.get_config("iso")
    cam.get_config("iso")
    cam.fail_next("capture", exc=CameraTimeout())
    with pytest.raises(CameraTimeout):
        cam.capture()
    cam.capture()
    assert cam.calls["get_config"] == 3 and cam.calls["capture"] == 2
    with pytest.raises(ValueError):
        cam.fail_next("bogus")


def _run(fn: Callable[[], object], done: threading.Event) -> Callable[[], None]:
    def go() -> None:
        fn()
        done.set()

    return go


def test_hang_and_release(cam: FakeCamera) -> None:
    ev = cam.hang("summary")
    done = threading.Event()
    t = threading.Thread(target=_run(cam.summary, done), daemon=True)
    t.start()
    assert not done.wait(0.1)
    ev.set()
    assert done.wait(2)
    t.join(2)

    cam.hang("model")
    done2 = threading.Event()
    t2 = threading.Thread(target=_run(cam.model, done2), daemon=True)
    t2.start()
    assert not done2.wait(0.1)
    cam.release_all()
    assert done2.wait(2)
    t2.join(2)
    cam.model()  # no longer hangs


def test_unplug_replug() -> None:
    c = FakeCamera()
    c.open()
    c.unplug()
    with pytest.raises(CameraIOError):
        c.capture()
    with pytest.raises(CameraNotFound):
        c.open()
    c.close()
    c.replug()
    c.open()
    c.capture()


def test_latency(cam: FakeCamera) -> None:
    import time

    cam.set_latency("model", 0.1)
    t0 = time.monotonic()
    cam.model()
    assert time.monotonic() - t0 >= 0.09
    cam.set_latency("model", 0)


def test_card_full(cam: FakeCamera) -> None:
    cam.card_full()
    assert cam.storage_info()[0].free_kb == 0
    with pytest.raises(StorageFull):
        cam.capture()
    cam.card_full(False)
    cam.capture()


def test_exposurecompensation_choices_are_libgphoto2_format_regression(cam: FakeCamera) -> None:
    ch = cam.get_config("exposurecompensation").choices
    assert "1" in ch and "0.333" in ch and "-0.667" in ch and "0" in ch
    assert not any(c.startswith("+") for c in ch)
    with pytest.raises(SettingInvalid):
        cam.set_config("exposurecompensation", "+1")


def test_capture_exits_liveview_needs_reenable() -> None:
    c = FakeCamera()
    c.open()
    c.capture_preview()
    assert c.viewfinder_on
    c.capture()
    assert not c.viewfinder_on
    with pytest.raises(CameraOperationFailed):  # stale flag: viewfinder not re-enabled
        c.capture_preview()
    c.invalidate_preview()
    c.capture_preview()
    assert c.viewfinder_on
    c.end_preview()
    assert not c.viewfinder_on and c.calls["end_preview"] == 1


def test_capture_keeps_liveview_when_option_off() -> None:
    c = FakeCamera(capture_exits_liveview=False)
    c.open()
    c.capture_preview()
    c.capture()
    assert c.viewfinder_on
