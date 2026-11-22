import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.api.schemas.common import EventType
from backend.api.schemas.presets import (
    BracketPresetIn,
    PresetImportIn,
    SettingsPresetIn,
)
from backend.api.schemas.timelapse import QuickBracketing
from backend.core.errors import Forbidden, InvalidState, PresetNotFound, SettingNotAllowed
from backend.core.events import EventBus
from backend.services.presets import FILE_NAME, PresetService


def leftovers(d: Path, pattern: str) -> list[Path]:
    return list(d.glob(pattern))


def svc(d: Path) -> PresetService:
    return PresetService(d, MagicMock())


def sp(name: str = "Night", **v: object) -> SettingsPresetIn:
    return SettingsPresetIn(name=name, values=v or {"iso": 3200})  # type: ignore[arg-type]


async def test_persists_across_instances(tmp_path: Path) -> None:
    p = await svc(tmp_path).create(sp())
    again = await svc(tmp_path).get(p.id)
    assert again.name == "Night" and again.created is not None
    assert not leftovers(tmp_path, "*.tmp")


async def test_aliases_normalised_and_unwritable_rejected(tmp_path: Path) -> None:
    p = await svc(tmp_path).create(sp("a", aperture="f/2.8"))
    assert p.kind == "settings" and "f-number" in p.values
    with pytest.raises(SettingNotAllowed):
        await svc(tmp_path).create(sp("b", capturetarget="Memory card"))


async def test_name_unique_per_kind_case_insensitive(tmp_path: Path) -> None:
    s = svc(tmp_path)
    await s.create(sp("Night"))
    with pytest.raises(InvalidState):
        await s.create(sp("night"))
    b = BracketPresetIn(name="Night", bracketing=QuickBracketing(iso=["100", "200"]))
    await s.create(b)  # other kind: fine
    with pytest.raises(InvalidState):  # clashes with a built-in bracket name
        await s.create(BracketPresetIn(name="exposure_3", bracketing=b.bracketing))


async def test_corrupt_file_moved_aside_not_fatal(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_text("{not json")
    s = svc(tmp_path)
    out = await s.list("settings")
    assert out.items == [] and out.warning and "moved" in out.warning
    assert leftovers(tmp_path, f"{FILE_NAME}.corrupt-*")
    await s.create(sp())  # usable afterwards
    assert json.loads((tmp_path / FILE_NAME).read_text())["schema_version"] == 1


async def test_bad_items_skipped_on_load(tmp_path: Path) -> None:
    good = await svc(tmp_path).create(sp())
    doc = json.loads((tmp_path / FILE_NAME).read_text())
    doc["presets"].append({"id": "x", "kind": "nope"})
    (tmp_path / FILE_NAME).write_text(json.dumps(doc))
    out = await svc(tmp_path).list("settings")
    assert [p.id for p in out.items] == [good.id] and "skipped" in (out.warning or "")


async def test_get_unknown(tmp_path: Path) -> None:
    with pytest.raises(PresetNotFound):
        await svc(tmp_path).get("nope")


async def test_import_replace_and_merge(tmp_path: Path) -> None:
    s = svc(tmp_path)
    await s.create(sp("old"))
    doc = PresetImportIn(
        replace=True,
        presets=[
            {"kind": "settings", "name": "new", "values": {"iso": 100}},
            {"kind": "settings", "name": "bad", "values": {}},
            {"kind": "settings", "name": "new", "values": {"iso": 200}},
        ],
    )
    r = await s.import_(doc)
    assert (r.created, r.failed, r.skipped) == (1, 1, 1)
    assert [p.name for p in (await s.list("settings")).items] == ["new"]


async def test_unreadable_file_refuses_writes_instead_of_overwriting(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).mkdir()  # exists but cannot be read (OSError)
    s = svc(tmp_path)
    out = await s.list()
    assert out.warning and "unreadable" in out.warning
    with pytest.raises(InvalidState, match="cannot be read"):
        await s.create(sp())
    assert (tmp_path / FILE_NAME).is_dir()  # untouched
    (tmp_path / FILE_NAME).rmdir()  # fixed: readable again, writes work
    await s.create(sp())
    assert json.loads((tmp_path / FILE_NAME).read_text())["presets"]


async def test_skipped_entries_are_backed_up_before_first_rewrite(tmp_path: Path) -> None:
    await svc(tmp_path).create(sp())
    doc = json.loads((tmp_path / FILE_NAME).read_text())
    doc["presets"].append({"id": "x", "kind": "nope", "keep": "me"})
    original = json.dumps(doc)
    (tmp_path / FILE_NAME).write_text(original)
    s = svc(tmp_path)
    await s.create(sp("second"))
    baks = leftovers(tmp_path, f"{FILE_NAME}.bak-*")
    assert len(baks) == 1 and baks[0].read_text() == original
    out = await s.list()
    assert "skipped" in (out.warning or "") and baks[0].name in (out.warning or "")
    await s.create(sp("third"))
    assert len(leftovers(tmp_path, f"{FILE_NAME}.bak-*")) == 1  # only before the first rewrite


async def test_builtin_modification_is_forbidden_not_setting_error(tmp_path: Path) -> None:
    with pytest.raises(Forbidden):
        await svc(tmp_path).delete("builtin-exposure_3")


async def test_presets_changed_event_on_create_update_delete_import(tmp_path: Path) -> None:
    bus = EventBus()
    sub = bus.subscribe()
    s = PresetService(tmp_path, MagicMock(), bus=bus)
    p = await s.create(sp())
    await s.update(p.id, sp("Renamed"))
    await s.delete(p.id)
    await s.import_(
        PresetImportIn(presets=[{"kind": "settings", "name": "i", "values": {"iso": 1}}])
    )
    got = [await asyncio.wait_for(anext(sub), 1) for _ in range(4)]
    sub.close()
    assert [e.type for e in got] == [EventType.PRESETS_CHANGED] * 4
    assert [e.data["action"] for e in got] == ["created", "updated", "deleted", "imported"]
    assert got[0].data["id"] == p.id and got[0].data["kind"] == "settings"
