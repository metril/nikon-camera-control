import pytest

from backend.camera.backend import ConfigRange, ConfigType, ConfigWidget
from backend.core.camera_service import CameraService
from backend.core.errors import SettingInvalid, SettingNotAllowed
from backend.services.settings import SettingsService, resolve_name, validate_value


def W(t: ConfigType, **kw: object) -> ConfigWidget:
    return ConfigWidget(name="w", label="w", path="/w", type=t, **kw)  # type: ignore[arg-type]


def test_toggle_requires_real_bool_regression() -> None:
    w = W(ConfigType.TOGGLE, value=False)
    assert validate_value(w, True) is True
    for bad in ("True", 1, 0, "true"):
        with pytest.raises(SettingInvalid):
            validate_value(w, bad)


def test_range_bounds_and_step() -> None:
    w = W(ConfigType.RANGE, range=ConfigRange(0, 10, 2))
    assert validate_value(w, 4) == 4.0
    for bad in (11, -2, 3, "4", True):
        with pytest.raises(SettingInvalid):
            validate_value(w, bad)


def test_choice() -> None:
    w = W(ConfigType.RADIO, choices=("100", "200"))
    assert validate_value(w, 200) == "200" and validate_value(w, 200.0) == "200"
    with pytest.raises(SettingInvalid):
        validate_value(w, "300")


def test_date_int_or_iso() -> None:
    w = W(ConfigType.DATE)
    assert validate_value(w, 1700000000) == 1700000000
    assert validate_value(w, "2023-11-14T22:13:20Z") == 1700000000
    with pytest.raises(SettingInvalid):
        validate_value(w, "yesterday")
    with pytest.raises(SettingInvalid):
        validate_value(w, 1.5)


def test_resolve_name() -> None:
    assert resolve_name("aperture") == "f-number" and resolve_name("iso") == "iso"


async def test_snapshot_restore_real_prior_values(app, client) -> None:
    cam: CameraService = app.state.camera_service
    await cam.connect()
    svc = SettingsService(cam)
    snap = await svc.snapshot(["iso", "aperture"])
    assert snap == {"iso": "100", "f-number": "f/5.6"}
    await svc.set_many({"iso": "1600", "aperture": "f/16"})
    await svc.restore(snap)
    assert (await svc.get("iso")).value == "100"
    assert (await svc.get("aperture")).value == "f/5.6"
    with pytest.raises(SettingNotAllowed):
        await svc.set("capturetarget", "Internal RAM")
    async with cam.lease("tl"):
        await svc.set("iso", "200", owner="tl")
        await svc.restore(snap, owner="tl")
    assert (await svc.get("iso")).value == "100"
