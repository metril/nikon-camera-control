import pytest

from backend.api.schemas.timelapse import BracketStep, QuickBracketing
from backend.core.errors import ConfigInvalid
from backend.services.timelapse.brackets import (
    PRESETS,
    generate_quick,
    min_interval,
    normalise_steps,
    preset_steps,
    touched_settings,
)


def q(**kw: object) -> QuickBracketing:
    return QuickBracketing(**kw)  # type: ignore[arg-type]


def test_sequence_concatenates_types_in_order_with_legacy_labels() -> None:
    steps = generate_quick(
        q(exposure=["-2", "0"], iso=["100"], aperture=["f/2.8"], shutter=["1/250"])
    )
    assert [(s.settings, s.label) for s in steps] == [
        ({"exposurecompensation": "-2"}, "-2 EV"),
        ({"exposurecompensation": "0"}, "0 EV"),
        ({"iso": "100"}, "ISO 100"),
        ({"aperture": "f/2.8"}, "f/2.8"),
        ({"shutterspeed": "1/250"}, "1/250"),
    ]


def test_paired_zips_by_index_and_shorter_lists_stop_contributing() -> None:
    steps = generate_quick(q(exposure=["-2", "0", "+2"], iso=["100", "400"], combine_mode="paired"))
    assert [(s.settings, s.label) for s in steps] == [
        ({"exposurecompensation": "-2", "iso": "100"}, "EV-2 / ISO 100"),
        ({"exposurecompensation": "0", "iso": "400"}, "EV0 / ISO 400"),
        ({"exposurecompensation": "+2"}, "EV+2"),
    ]


def test_missing_or_empty_types_are_disabled() -> None:
    assert generate_quick(q()) == []
    assert generate_quick(q(iso=[], exposure=None, combine_mode="paired")) == []
    assert [s.settings for s in generate_quick(q(iso=["100", "200"], aperture=[]))] == [
        {"iso": "100"},
        {"iso": "200"},
    ]


def test_all_builtin_presets_are_valid_brackets() -> None:
    assert {"exposure_3", "exposure_7", "iso_3", "hdr_iso_combo", "aperture_sweep"} <= set(PRESETS)
    for name in PRESETS:
        steps = normalise_steps(preset_steps(name))
        assert 2 <= len(steps) <= 15 and all(s.settings for s in steps)
    assert preset_steps("hdr_iso_combo")[3].settings == {"exposurecompensation": "0", "iso": "800"}
    assert normalise_steps(preset_steps("aperture_sweep"))[0].settings == {"f-number": "f/2.8"}
    with pytest.raises(ConfigInvalid):
        preset_steps("nope")


def test_empty_settings_step_and_bad_counts_rejected_regression() -> None:
    # old bug: a step without settings counted as a done set
    with pytest.raises(ConfigInvalid):
        normalise_steps([BracketStep.model_construct(settings={}, label="", delay_ms=0)] * 2)
    one = BracketStep(settings={"iso": "100"})
    with pytest.raises(ConfigInvalid):
        normalise_steps([one])
    with pytest.raises(ConfigInvalid):
        normalise_steps([])
    with pytest.raises(ConfigInvalid):
        normalise_steps([one] * 16)
    with pytest.raises(ConfigInvalid):  # alias + widget name collide
        normalise_steps([BracketStep(settings={"aperture": "f/4", "f-number": "f/5.6"}), one])


def test_touched_and_min_interval() -> None:
    steps = normalise_steps(preset_steps("hdr_iso_combo"))
    assert touched_settings(steps) == ["exposurecompensation", "iso"]
    assert min_interval([], 1.0) == 1.0
    assert min_interval(steps, 1.0) > min_interval(steps[:2], 1.0) > 1.0
    delayed = [BracketStep(settings={"iso": "100"}, delay_ms=5000)] * 2
    assert min_interval(delayed, 1.0) > 12


def test_presets_are_camera_neutral_decimals_regression() -> None:
    """No camera-specific spellings ("+1"): the camera's own choice string is resolved later."""
    from backend.services.timelapse.brackets import PRESETS

    for p in PRESETS.values():
        for step in p.steps:
            ev = step.settings.get("exposurecompensation")
            if ev is not None:
                assert isinstance(ev, str) and not ev.startswith("+")
                float(ev)


def test_time_model_constants_are_module_level() -> None:
    from backend.services.timelapse import brackets

    assert (brackets.SHOT_ESTIMATE_S, brackets.SETTLE_S, brackets.RESTORE_S) == (1.0, 0.3, 0.5)
