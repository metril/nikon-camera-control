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


CH = ("-0.667", "-0.333", "0", "0.333", "0.667", "1", "1.33", "2")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("+1", "1"), (1, "1"), ("+2", "2"), (-0.667, "-0.667"), ("1/3", "0.333"), ("+0", "0"),
     ("0.3333", "0.333"), ("+1.3333", "1.33"), ("+0.333", "0.333"), ("0.33", "0.333"),
     ("+0.7", "0.667")],
)  # fmt: skip
def test_exposure_comp_tolerant_match_regression(value: object, expected: str) -> None:
    assert validate_value(W(ConfigType.RADIO, choices=CH), value) == expected


def test_aperture_and_shutter_tolerant_match() -> None:
    ap = W(ConfigType.RADIO, choices=("f/1.4", "f/2.8", "f/5.6"))
    assert validate_value(ap, "2.8") == "f/2.8" and validate_value(ap, 2.8) == "f/2.8"
    assert validate_value(ap, "F/5.6") == "f/5.6"
    sh = W(ConfigType.RADIO, choices=("1/250", "1/500", "0.0040s", "30", "Bulb"))
    assert validate_value(sh, "1/500") == "1/500"  # exact wins
    sh2 = W(ConfigType.RADIO, choices=("0.0040s", "0.0020s", "30s", "Bulb"))
    assert validate_value(sh2, "1/250") == "0.0040s"
    assert validate_value(sh2, "30") == "30s" and validate_value(sh2, "bulb") == "Bulb"


def test_no_or_ambiguous_match_lists_nearby_choices() -> None:
    w = W(ConfigType.RADIO, choices=CH)
    with pytest.raises(SettingInvalid) as ei:
        validate_value(w, "+1.7")
    assert "1.33" in ei.value.details["nearby"] and len(ei.value.details["nearby"]) <= 5
    amb = W(ConfigType.RADIO, choices=("1", "1.0", "2"))
    with pytest.raises(SettingInvalid):
        validate_value(amb, "+1")


async def test_set_with_signed_spelling_sends_canonical_choice(app, client) -> None:
    cam: CameraService = app.state.camera_service
    await cam.connect()
    svc = SettingsService(cam)
    assert (await svc.set("exposurecompensation", "+1")).value == "1"
    res = await svc.set_many({"exposurecompensation": "-1.3333", "aperture": "2.8"})
    assert {v.name: v.value for v in res.applied} == {
        "exposurecompensation": "-1.33",
        "f-number": "f/2.8",
    }


async def test_bracket_sequence_does_zero_list_config_after_first_regression(
    app, client, fake_camera
) -> None:
    cam: CameraService = app.state.camera_service
    await cam.connect()
    svc = SettingsService(cam)
    await svc.list_settings()
    base = fake_camera.calls["list_config"]
    snap = await svc.snapshot(["iso", "exposurecompensation", "shutterspeed"])
    for ev in ("-2", "0", "+2"):
        await svc.set_many({"exposurecompensation": ev, "iso": "800"})
        await svc.get("exposurecompensation")
    await svc.restore(snap)
    assert (await svc.get("iso")).value == "100"
    assert fake_camera.calls["list_config"] == base == 1


async def test_mode_like_write_refetches_tree(app, client, fake_camera) -> None:
    cam: CameraService = app.state.camera_service
    await cam.connect()
    svc = SettingsService(cam)
    await svc.list_settings()
    await svc.set("focusmode", "AF-C")
    await svc.get("iso")
    assert fake_camera.calls["list_config"] == 2
    await svc.refresh()
    assert fake_camera.calls["list_config"] == 3


ISO = W(ConfigType.RADIO, choices=("100", "102", "800", "1000", "1250"))


def test_integer_values_must_match_exactly_regression() -> None:
    for bad in ("999", 999, 101, "+999"):
        with pytest.raises(SettingInvalid) as ei:
            validate_value(ISO, bad)
        assert ei.value.details["nearby"]
    assert validate_value(ISO, "1000") == "1000" and validate_value(ISO, 1000) == "1000"
    assert validate_value(ISO, 1000.0) == "1000" and validate_value(ISO, 100) == "100"


def test_midway_value_is_ambiguous_regression() -> None:
    w = W(ConfigType.RADIO, choices=("0", "0.333", "0.667"))
    with pytest.raises(SettingInvalid) as ei:
        validate_value(w, "0.5")
    assert set(ei.value.details["nearby"]) >= {"0.333", "0.667"}
