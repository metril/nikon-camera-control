"""Camera/libgphoto2-reported text: display normalisation and documented manual references.

Nothing here infers causes. Text is only re-cased/split for display; the raw strings are kept by
callers. Guidance is limited to ``NIKON_MANUAL`` entries, each citing the D500 User's Manual
(English, v06, https://download.nikonimglib.com/archive3/4qUKV00WD5Bh04RdeC800lRubd09/D500UM_NT(En)06.pdf).
"""

from __future__ import annotations

import re
from typing import Any

# Reason strings libgphoto2 (ptp2 config.c) can emit for the prohibit widgets / liveview errors.
# Used to split lists: one of them contains a comma itself.
KNOWN_REASONS: tuple[str, ...] = (
    "Battery exhausted",
    "Temperature too high",
    "TTL error",
    "In Mirror-up operation",
    "Lens is retracting",
    "Minimum aperture warning",
    "Processing of shooting operation",
    "Sequence error",
    "Exposure Program Mode is not P/A/S/M",
    "Bulb warning",
    "Card unformatted",
    "Card error",
    "Card protected",
    "Recording destination card, but no card or card protected",
    "Pending unretrieved SDRAM image",
    "Fully pressed button",
    "Set liveview selector is enabled",
    "In enlarged liveview",
    "Images / movies not yet record in buffer",
)

# Lower-cased camera text -> documented note. Only entries stated in the D500 manual.
NIKON_MANUAL: dict[str, str] = {
    "battery exhausted": (
        "D500 manual p.35 (Battery Level): shutter release is disabled when the battery "
        "is exhausted."
    ),
}

_LIVE_VIEW = re.compile(r"\blive\s?view\b", re.IGNORECASE)
_WORD = re.compile(r"[^\s]+")
_NEUTRAL = ("liveview should not be prohibited", "no movie prohibit conditions")
_PREFIXES = ("live view prohibit conditions:", "movie prohibit conditions:")


def _word(w: str) -> str:
    # Keep acronyms/units (any uppercase after the first character, e.g. SDRAM, TTL, P/A/S/M).
    return w if any(c.isupper() for c in w[1:]) else w.lower()


def sentence_case(text: str) -> str:
    """Sentence case without changing wording; "Live view" spelling; acronyms kept."""
    t = _LIVE_VIEW.sub("live view", text.strip())
    t = _WORD.sub(lambda m: _word(m.group()), t)
    t = re.sub(r"(^|:\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    return t


def split_reasons(text: str) -> list[str]:
    """Split a camera reason list on the known reason strings (not blindly on commas)."""
    rest = text.strip()
    out: list[str] = []
    while rest:
        low = rest.lower()
        hit = max((r for r in KNOWN_REASONS if low.startswith(r.lower())), key=len, default=None)
        if hit is not None:
            out.append(rest[: len(hit)])
            rest = rest[len(hit) :]
        else:
            head, _, rest = rest.partition(",")
            if head.strip():
                out.append(head)
            continue
        rest = rest.lstrip(" ,")
    return [sentence_case(r) for r in out if r.strip()]


def prohibit_reasons(value: object) -> tuple[str, list[str]]:
    """(raw text, reasons) of a liveviewprohibit/movieprohibit widget value. No reasons when the
    camera reports none."""
    raw = str(value or "").strip()
    low = raw.lower()
    if not raw or low.startswith(_NEUTRAL):
        return raw, []
    for p in _PREFIXES:
        if low.startswith(p):
            raw_reasons = raw[len(p) :]
            return raw, split_reasons(raw_reasons)
    return raw, split_reasons(raw)


def manual_note(texts: list[str]) -> str | None:
    """Documented manual note for camera-reported ``texts`` (raw or normalised), if any."""
    for key, note in NIKON_MANUAL.items():
        if any(key in t.lower() for t in texts):
            return note
    return None


def camera_details(raw_messages: list[str]) -> dict[str, Any]:
    """Error-details entries for messages libgphoto2 reported through the context."""
    if not raw_messages:
        return {}
    d: dict[str, Any] = {
        "camera_message": "; ".join(sentence_case(m) for m in raw_messages),
        "camera_message_raw": "; ".join(raw_messages),
    }
    if (note := manual_note(raw_messages)) is not None:
        d["nikon_manual"] = note
    return d


def refusal_message(what: str, reasons: list[str]) -> str:
    return f"The camera refused {what}. Camera reports: {'; '.join(reasons)}"


def apply_prohibit(details: dict[str, Any], what: str, raw: str, reasons: list[str]) -> str | None:
    """Add prohibit entries to ``details``; return the new message, or None when the camera
    reported no reasons."""
    if not reasons:
        return None
    details["prohibit"] = "; ".join(reasons)
    details["prohibit_raw"] = raw
    note = manual_note([*reasons, str(details.get("camera_message_raw", ""))])
    if note is not None:
        details["nikon_manual"] = note
    return refusal_message(what, reasons)
