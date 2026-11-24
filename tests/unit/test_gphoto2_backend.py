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
    CameraOperationFailed,
    CameraTimeout,
    FeatureUnsupported,
    FileNotFoundError_,
    SettingInvalid,
    SettingNotAllowed,
    SettingNotFound,
    StorageFull,
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
        (gp.GP_ERROR_IO_USB_FIND, CameraIOError),
        (gp.GP_ERROR_IO_USB_CLEAR_HALT, CameraIOError),
        (gp.GP_ERROR_CAMERA_ERROR, CameraOperationFailed),
        (gp.GP_ERROR_CORRUPTED_DATA, CameraOperationFailed),
        (gp.GP_ERROR_BAD_PARAMETERS, CameraOperationFailed),
        (gp.GP_ERROR_NO_SPACE, StorageFull),
        (-12345, CameraOperationFailed),
    ],
)
def test_translate_error(code: int, exc: type[Exception]) -> None:
    out = translate_error(gp.GPhoto2Error(code), "op")
    assert type(out) is exc
    assert out.details["gphoto2_code"] == code


def test_set_config_bad_parameters_is_setting_invalid() -> None:
    class Cam(FakeCamera):
        def set_single_config(self, name: str, w: StubWidget, ctx: Any) -> None:
            raise gp.GPhoto2Error(gp.GP_ERROR_BAD_PARAMETERS)

    with pytest.raises(SettingInvalid):
        _backend(Cam(_root())).set_config("iso", "200")


def test_failed_operation_does_not_look_like_link_loss() -> None:
    class Cam:
        def trigger_capture(self, ctx: Any) -> None:
            raise gp.GPhoto2Error(gp.GP_ERROR_CAMERA_ERROR)

        def capture(self, t: int, ctx: Any) -> None:
            raise gp.GPhoto2Error(gp.GP_ERROR_NO_SPACE)

    b = _backend(Cam())
    with pytest.raises(CameraOperationFailed) as ei:
        b.trigger()
    assert not isinstance(ei.value, CameraIOError)
    with pytest.raises(StorageFull):
        b.capture()


def test_unknown_widget_type_is_unknown() -> None:
    w = widget_to_config(StubWidget("weird", 999, "x"))
    assert w.type is ConfigType.UNKNOWN


def test_binding_calls_match_installed_signatures(tmp_path: Path) -> None:
    # capture_preview/file_get take an optional CameraFile, NOT the context, in this binding.
    class Cam:
        def capture_preview(self, *args: Any) -> Any:
            assert not args

            class F:
                def get_data_and_size(self) -> bytes:
                    return b"jpg"

            return F()

        def file_get(self, folder: str, name: str, t: int, *args: Any) -> Any:
            assert not args

            class F:
                def save(self, path: str) -> None:
                    Path(path).write_bytes(b"x")

            return F()

    b = _backend(Cam())
    b._viewfinder_on = True
    assert b.capture_preview() == b"jpg"
    dest = tmp_path / "p.jpg"
    b.read_file("/f", "a.jpg", FileKind.PREVIEW, dest)
    assert dest.read_bytes() == b"x"


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


def test_end_preview_clears_viewfinder_and_flag() -> None:
    vf = StubWidget("viewfinder", gp.GP_WIDGET_TOGGLE, 1)
    root = StubWidget(
        "main",
        gp.GP_WIDGET_WINDOW,
        children=(StubWidget("actions", gp.GP_WIDGET_SECTION, children=(vf,)),),
    )
    cam = FakeCamera(root)
    b = _backend(cam)
    b._viewfinder_on = True
    b.end_preview()
    assert cam.set_calls == [("viewfinder", 0)] and not b._viewfinder_on


def test_end_preview_without_viewfinder_widget_is_quiet_and_resets_flag() -> None:
    b = _backend(FakeCamera(_root()))
    b._viewfinder_on = True
    b.end_preview()  # no "viewfinder" widget on this body
    assert not b._viewfinder_on


def test_invalidate_preview_makes_next_preview_reenable() -> None:
    vf = StubWidget("viewfinder", gp.GP_WIDGET_TOGGLE, 0)
    root = StubWidget(
        "main",
        gp.GP_WIDGET_WINDOW,
        children=(StubWidget("actions", gp.GP_WIDGET_SECTION, children=(vf,)),),
    )

    class Cam(FakeCamera):
        def capture_preview(self) -> Any:
            class F:
                def get_data_and_size(self) -> bytes:
                    return b"j"

            return F()

    c2 = Cam(root)
    b = _backend(c2)
    b.capture_preview()
    b.invalidate_preview()
    b.capture_preview()
    assert [n for n, _ in c2.set_calls] == ["viewfinder", "viewfinder"]


def test_read_file_falls_back_to_whole_file_when_partial_read_fails(tmp_path: Path) -> None:
    class Info:
        class file:  # noqa: N801
            size = 100

    class Cam:
        def file_get_info(self, f: str, n: str, ctx: Any) -> Any:
            return Info

        def file_read(self, *a: Any) -> int:
            raise gp.GPhoto2Error(-1)

        def file_get(self, folder: str, name: str, t: int, *args: Any) -> Any:
            class F:
                def save(self, path: str) -> None:
                    Path(path).write_bytes(b"whole")

            return F()

    dest = tmp_path / "capt0000.jpg"
    _backend(Cam()).read_file("/", "capt0000.jpg", FileKind.NORMAL, dest)
    assert dest.read_bytes() == b"whole" and not list(tmp_path.glob("*.part"))


def test_read_file_error_path_has_no_double_slash(tmp_path: Path) -> None:
    class Cam:
        def file_get_info(self, *a: Any) -> Any:
            raise gp.GPhoto2Error(-1)

        def file_get(self, *a: Any) -> Any:
            raise gp.GPhoto2Error(-1)

    with pytest.raises(CameraOperationFailed) as ei:
        _backend(Cam()).read_file("/", "capt0000.jpg", FileKind.NORMAL, tmp_path / "x")
    assert "read_file(/capt0000.jpg)" in ei.value.message and "//" not in ei.value.message


def test_partial_read_failure_midway_leaves_exact_whole_file(tmp_path: Path) -> None:
    class Info:
        class file:  # noqa: N801
            size = 4000

    class Cam:
        def file_get_info(self, f: str, n: str, ctx: Any) -> Any:
            return Info

        def file_read(self, f: str, n: str, t: int, off: int, buf: memoryview, ctx: Any) -> int:
            if off:
                raise gp.GPhoto2Error(-1)
            buf[:10] = b"x" * 10
            return 10

        def file_get(self, folder: str, name: str, t: int, *args: Any) -> Any:
            class F:
                def save(self, path: str) -> None:
                    Path(path).write_bytes(b"whole-file")

            return F()

    dest = tmp_path / "a.jpg"
    _backend(Cam()).read_file("/", "a.jpg", FileKind.NORMAL, dest)
    assert dest.read_bytes() == b"whole-file"


def test_fallback_failure_reports_both_causes(tmp_path: Path) -> None:
    class Cam:
        def file_get_info(self, *a: Any) -> Any:
            raise gp.GPhoto2Error(-1)

        def file_get(self, *a: Any) -> Any:
            raise gp.GPhoto2Error(-1)

    with pytest.raises(CameraOperationFailed) as ei:
        _backend(Cam()).read_file("/", "a.jpg", FileKind.NORMAL, tmp_path / "x")
    assert {"partial_read_cause", "whole_file_cause"} <= set(ei.value.details)
