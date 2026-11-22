from __future__ import annotations

from pathlib import Path
from typing import Any

import gphoto2 as gp
import pytest

from backend.camera.backend import (
    CameraBackend,
    ConfigRange,
    ConfigType,
    ConfigWidget,
    EventType,
    FileKind,
)
from backend.camera.gphoto2_backend import (
    Gphoto2Backend,
    coerce_config_value,
    translate_error,
    widget_to_config,
)
from backend.core.errors import (
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


class StubWidget:
    def __init__(
        self,
        name: str,
        wtype: int,
        value: Any = None,
        choices: tuple[str, ...] = (),
        rng: tuple[float, float, float] | None = None,
        readonly: int = 0,
        children: tuple[StubWidget, ...] = (),
    ) -> None:
        self.name, self.wtype, self.value = name, wtype, value
        self.choices, self.rng, self.readonly, self.children = choices, rng, readonly, children
        self.parent: StubWidget | None = None
        for c in children:
            c.parent = self

    def get_parent(self) -> StubWidget | None:
        return self.parent

    def get_type(self) -> int:
        return self.wtype

    def get_name(self) -> str:
        return self.name

    def get_label(self) -> str:
        return self.name.upper()

    def get_readonly(self) -> int:
        return self.readonly

    def set_value(self, v: Any) -> None:
        self.value = v

    def get_value(self) -> Any:
        return self.value

    def count_choices(self) -> int:
        return len(self.choices)

    def get_choice(self, i: int) -> str:
        return self.choices[i]

    def get_range(self) -> tuple[float, float, float]:
        assert self.rng
        return self.rng

    def count_children(self) -> int:
        return len(self.children)

    def get_child(self, i: int) -> StubWidget:
        return self.children[i]


class FakeCamera:
    """Minimal stand-in for gp.Camera, only what the tested paths touch."""

    def __init__(self, root: StubWidget, single: bool = True) -> None:
        self.root, self.single = root, single
        self.set_calls: list[tuple[str, Any]] = []

    def get_single_config(self, name: str, ctx: Any) -> StubWidget:
        if not self.single:
            raise gp.GPhoto2Error(gp.GP_ERROR_NOT_SUPPORTED)
        for sec in self.root.children:
            for w in sec.children:
                if w.name == name:
                    return w
        raise gp.GPhoto2Error(gp.GP_ERROR_BAD_PARAMETERS)

    def get_config(self, ctx: Any) -> Any:
        root = self.root

        class R:
            def get_child_by_name(self_, name: str) -> StubWidget:  # noqa: N805
                for sec in root.children:
                    for w in sec.children:
                        if w.name == name:
                            return w
                raise gp.GPhoto2Error(gp.GP_ERROR_BAD_PARAMETERS)

        return R()

    def set_single_config(self, name: str, w: StubWidget, ctx: Any) -> None:
        self.set_calls.append((name, w.value))


def _root() -> StubWidget:
    iso = StubWidget("iso", gp.GP_WIDGET_RADIO, "100", ("100", "200", "400"))
    ro = StubWidget("batterylevel", gp.GP_WIDGET_TEXT, "50%", readonly=1)
    return StubWidget(
        "main",
        gp.GP_WIDGET_WINDOW,
        children=(StubWidget("imgsettings", gp.GP_WIDGET_SECTION, children=(iso, ro)),),
    )


def _backend(cam: Any) -> Gphoto2Backend:
    b = Gphoto2Backend()
    b._camera = cam
    return b


def test_satisfies_protocol() -> None:
    assert isinstance(Gphoto2Backend(), CameraBackend)


@pytest.mark.parametrize(
    ("code", "exc"),
    [
        (gp.GP_ERROR_MODEL_NOT_FOUND, CameraNotFound),
        (gp.GP_ERROR_CAMERA_BUSY, CameraBusy),
        (gp.GP_ERROR_IO_USB_CLAIM, CameraBusy),
        (gp.GP_ERROR_TIMEOUT, CameraTimeout),
        (gp.GP_ERROR_IO, CameraIOError),
        (gp.GP_ERROR_IO_READ, CameraIOError),
        (gp.GP_ERROR_FILE_NOT_FOUND, FileNotFoundError_),
        (gp.GP_ERROR_NOT_SUPPORTED, FeatureUnsupported),
        (gp.GP_ERROR_CAMERA_ERROR, CameraIOError),
    ],
)
def test_translate_error(code: int, exc: type[Exception]) -> None:
    out = translate_error(gp.GPhoto2Error(code), "op")
    assert type(out) is exc
    assert out.details["gphoto2_code"] == code


def test_widget_conversion_tree() -> None:
    tree = widget_to_config(_root())
    assert tree.path == "/main"
    sec = tree.children[0]
    assert sec.type is ConfigType.SECTION
    iso, ro = sec.children
    assert iso.path == "/main/imgsettings/iso"
    assert iso.choices == ("100", "200", "400") and iso.value == "100"
    assert ro.readonly


def test_widget_conversion_range_toggle() -> None:
    r = widget_to_config(StubWidget("r", gp.GP_WIDGET_RANGE, 1.0, rng=(0, 10, 0.5)))
    assert r.range == ConfigRange(0.0, 10.0, 0.5)
    assert widget_to_config(StubWidget("t", gp.GP_WIDGET_TOGGLE, 1)).value is True
    assert widget_to_config(StubWidget("t", gp.GP_WIDGET_TOGGLE, 2)).value is None


def _w(t: ConfigType, **kw: Any) -> ConfigWidget:
    return ConfigWidget(name="x", label="x", path="/x", type=t, **kw)


def test_coerce_radio() -> None:
    w = _w(ConfigType.RADIO, choices=("100", "400"))
    assert coerce_config_value(w, "100") == "100"
    assert coerce_config_value(w, 400) == "400"
    with pytest.raises(SettingInvalid):
        coerce_config_value(w, "800")
    with pytest.raises(SettingInvalid):
        coerce_config_value(w, True)


def test_coerce_range() -> None:
    w = _w(ConfigType.RANGE, range=ConfigRange(-3, 3, 0.5))
    assert coerce_config_value(w, 1) == 1.0
    assert coerce_config_value(w, -2.5) == -2.5
    for bad in (4, 0.3, "1"):
        with pytest.raises(SettingInvalid):
            coerce_config_value(w, bad)


def test_coerce_toggle_date_text() -> None:
    t = _w(ConfigType.TOGGLE)
    assert coerce_config_value(t, True) == 1
    assert coerce_config_value(t, 0) == 0
    with pytest.raises(SettingInvalid):
        coerce_config_value(t, 2)
    assert coerce_config_value(_w(ConfigType.DATE), 1700000000) == 1700000000
    with pytest.raises(SettingInvalid):
        coerce_config_value(_w(ConfigType.DATE), "2024-01-01")
    assert coerce_config_value(_w(ConfigType.TEXT), "hi") == "hi"
    with pytest.raises(SettingInvalid):
        coerce_config_value(_w(ConfigType.TEXT), 5)


def test_coerce_readonly() -> None:
    with pytest.raises(SettingNotAllowed):
        coerce_config_value(_w(ConfigType.TEXT, readonly=True), "a")


@pytest.mark.parametrize("single", [True, False])
def test_get_set_config(single: bool) -> None:
    cam = FakeCamera(_root(), single=single)
    b = _backend(cam)
    assert b.get_config("iso").path == "/main/imgsettings/iso"
    with pytest.raises(SettingNotFound):
        b.get_config("nope")
    with pytest.raises(SettingInvalid):
        b.set_config("iso", "999")
    with pytest.raises(SettingNotAllowed):
        b.set_config("batterylevel", "1")
    if single:
        b.set_config("iso", "200")
        assert cam.set_calls == [("iso", "200")]


def test_not_open_and_close_idempotent() -> None:
    b = Gphoto2Backend()
    assert not b.is_open
    with pytest.raises(CameraNotConnected):
        b.summary()
    b.close()
    b.close()


def test_close_after_io_error() -> None:
    class Dead:
        def exit(self, ctx: Any) -> None:
            raise gp.GPhoto2Error(gp.GP_ERROR_IO)

    b = _backend(Dead())
    b.close()
    b.close()
    assert not b.is_open


def test_wait_for_event_mapping() -> None:
    class Path_:
        folder, name = "/f", "a.nef"

    class Cam:
        def __init__(self, ev: tuple[int, Any]) -> None:
            self.ev = ev

        def wait_for_event(self, ms: int, ctx: Any) -> tuple[int, Any]:
            return self.ev

    cases = [
        ((gp.GP_EVENT_TIMEOUT, None), EventType.TIMEOUT),
        ((gp.GP_EVENT_FILE_ADDED, Path_()), EventType.FILE_ADDED),
        ((gp.GP_EVENT_CAPTURE_COMPLETE, None), EventType.CAPTURE_COMPLETE),
        ((gp.GP_EVENT_UNKNOWN, "x"), EventType.UNKNOWN),
    ]
    for ev, expected in cases:
        out = _backend(Cam(ev)).wait_for_event(0.5)
        assert out.type is expected
        if expected is EventType.FILE_ADDED:
            assert out.file is not None and out.file.name == "a.nef"


def test_read_file_chunked(tmp_path: Path) -> None:
    data = bytes(range(256)) * 10

    class Info:
        class file:  # noqa: N801
            size = len(data)

    class Cam:
        def file_get_info(self, f: str, n: str, ctx: Any) -> Any:
            return Info

        def file_read(self, f: str, n: str, t: int, off: int, buf: memoryview, ctx: Any) -> int:
            n_ = min(len(buf), 700)
            buf[:n_] = data[off : off + n_]
            return n_

    dest = tmp_path / "a.nef"
    _backend(Cam()).read_file("/f", "a.nef", FileKind.NORMAL, dest)
    assert dest.read_bytes() == data
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.hardware
def test_real_camera(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--real-camera", default=False):
        pytest.skip("needs --real-camera")
    b = Gphoto2Backend()
    b.open()
    try:
        assert b.model()
        assert b.summary()
        assert any(s.name == "imgsettings" for s in b.list_config())
        assert b.storage_info() is not None
    finally:
        b.close()
