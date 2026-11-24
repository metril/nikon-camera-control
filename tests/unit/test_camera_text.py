from __future__ import annotations

import pytest

from backend.camera.camera_text import (
    camera_details,
    manual_note,
    prohibit_reasons,
    sentence_case,
    split_reasons,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Liveview cannot start: Battery exhausted", "Live view cannot start: Battery exhausted"),
        ("Liveview should not be prohibited", "Live view should not be prohibited"),
        (
            "Live View prohibit conditions: Battery exhausted",
            "Live view prohibit conditions: Battery exhausted",
        ),
        ("Images/movies not yet record in buffer", "Images/movies not yet record in buffer"),
        ("Exposure Program Mode is not P/A/S/M", "Exposure program mode is not P/A/S/M"),
        ("Pending unretrieved SDRAM image", "Pending unretrieved SDRAM image"),
        ("TTL error", "TTL error"),
        ("In Mirror-up operation", "In mirror-up operation"),
    ],
)
def test_sentence_case(raw: str, expected: str) -> None:
    assert sentence_case(raw) == expected


def test_split_keeps_comma_inside_known_reason() -> None:
    raw = (
        "Battery exhausted, Recording destination card, "
        "but no card or card protected, Card protected"
    )
    assert split_reasons(raw) == [
        "Battery exhausted",
        "Recording destination card, but no card or card protected",
        "Card protected",
    ]


def test_split_unknown_reasons_on_commas() -> None:
    assert split_reasons("Some new reason, Another One") == ["Some new reason", "Another one"]


def test_prohibit_reasons() -> None:
    assert prohibit_reasons("Liveview should not be prohibited")[1] == []
    assert prohibit_reasons("No movie prohibit conditions")[1] == []
    assert prohibit_reasons("Live View prohibit conditions: Battery exhausted, Card protected")[
        1
    ] == ["Battery exhausted", "Card protected"]
    assert prohibit_reasons("Images / movies not yet record in buffer")[1] == [
        "Images / movies not yet record in buffer"
    ]


def test_manual_note_only_for_documented_entries() -> None:
    assert manual_note(["Liveview cannot start: Battery exhausted"]).startswith("D500 manual p.35")
    assert manual_note(["Card protected"]) is None
    assert camera_details([]) == {}
