import json
from typing import Any

import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.services.presets import FILE_NAME

P = "/api/v1/presets"
NIGHT = {"kind": "settings", "name": "Night sky", "values": {"iso": 3200, "aperture": "f/2.8"}}


async def make(c: httpx.AsyncClient, body: dict[str, Any] | None = None) -> dict[str, Any]:
    r = await c.post(P, json=body or NIGHT)
    assert r.status_code == 201, r.text
    return r.json()


async def test_operation_ids(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    ops = {o["operationId"] for p, v in paths.items() if p.startswith(P) for o in v.values()}
    assert ops == {
        "list_presets",
        "create_preset",
        "export_presets",
        "import_presets",
        "create_preset_from_camera",
        "get_preset",
        "update_preset",
        "delete_preset",
        "apply_preset",
    }


async def test_crud_and_unique_name(client: httpx.AsyncClient) -> None:
    p = await make(client)
    assert p["kind"] == "settings" and p["builtin"] is False and len(p["id"]) == 10
    assert p["values"]["f-number"] == "f/2.8"  # alias normalised
    assert (await client.get(f"{P}/{p['id']}")).json() == p
    r = await client.post(P, json=NIGHT)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATE"
    upd = {**NIGHT, "name": "Night 2", "description": "d"}
    r = await client.put(f"{P}/{p['id']}", json=upd)
    assert r.status_code == 200 and r.json()["name"] == "Night 2"
    assert r.json()["created"] == p["created"]
    r = await client.put(
        f"{P}/{p['id']}",
        json={
            "kind": "bracket",
            "name": "x",
            "bracketing": {"mode": "preset", "preset": "exposure_3"},
        },
    )
    assert r.status_code == 422  # kind cannot change
    assert (await client.delete(f"{P}/{p['id']}")).status_code == 200
    assert (await client.get(f"{P}/{p['id']}")).status_code == 404


async def test_name_length_and_bad_values(client: httpx.AsyncClient) -> None:
    for name in ("", "x" * 81, "   "):
        assert (await client.post(P, json={**NIGHT, "name": name})).status_code == 422
    r = await client.post(P, json={**NIGHT, "values": {"capturetarget": "Memory card"}})
    assert r.status_code == 403
    r = await client.post(
        P,
        json={
            "kind": "bracket",
            "name": "b",
            "bracketing": {"mode": "steps", "steps": [{"settings": {"iso": "100"}}]},
        },
    )
    assert r.status_code == 422  # needs 2+ steps


async def test_builtins_listed_and_immutable(client: httpx.AsyncClient) -> None:
    items = (await client.get(P, params={"kind": "bracket"})).json()["items"]
    b = next(i for i in items if i["id"] == "builtin-exposure_3")
    assert b["builtin"] is True and b["bracketing"] == {"mode": "preset", "preset": "exposure_3"}
    assert (await client.get(P, params={"kind": "settings"})).json()["items"] == []
    r = await client.delete(f"{P}/builtin-exposure_3")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    r = await client.put(
        f"{P}/builtin-exposure_3",
        json={
            "kind": "bracket",
            "name": "z",
            "bracketing": {"mode": "quick", "iso": ["100", "200"]},
        },
    )
    assert r.status_code == 403


async def test_id_validation(client: httpx.AsyncClient) -> None:
    for bad in ("..%2Fetc", "A_B", "a b", "x" * 80):
        r = await client.get(f"{P}/{bad}")
        assert r.status_code in (404, 422), bad
    assert (await client.get(f"{P}/Bad.Id")).status_code == 422


async def test_apply_settings_valid(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    p = await make(connected_client)
    r = await connected_client.post(f"{P}/{p['id']}/apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "settings" and {a["name"] for a in body["applied"]} == {
        "iso",
        "f-number",
    }
    assert fake_camera.get_config("iso").value == "3200"


async def test_apply_invalid_applies_nothing(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    before = fake_camera.get_config("iso").value
    p = await make(connected_client, {**NIGHT, "values": {"iso": 3200, "f-number": "f/99"}})
    r = await connected_client.post(f"{P}/{p['id']}/apply")
    assert r.status_code == 422 and r.json()["error"]["code"] == "SETTING_INVALID"
    assert fake_camera.get_config("iso").value == before


async def test_apply_requires_camera(client: httpx.AsyncClient) -> None:
    p = await make(client)
    r = await client.post(f"{P}/{p['id']}/apply")
    assert r.status_code == 503


async def test_apply_bracket_returns_resolved_steps(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    iso = fake_camera.get_config("iso").value
    r = await connected_client.post(f"{P}/builtin-iso_3/apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "bracket" and [s["settings"]["iso"] for s in body["steps"]] == [
        "200",
        "800",
        "3200",
    ]
    assert fake_camera.get_config("iso").value == iso  # nothing started or changed
    mine = await make(
        connected_client,
        {
            "kind": "bracket",
            "name": "mine",
            "bracketing": {"mode": "quick", "exposure": ["-1", "1"]},
        },
    )
    r = await connected_client.post(f"{P}/{mine['id']}/apply")
    assert len(r.json()["steps"]) == 2


async def test_from_camera(connected_client: httpx.AsyncClient, fake_camera: FakeCamera) -> None:
    r = await connected_client.post(f"{P}/from-camera", json={"name": "Now"})
    assert r.status_code == 201, r.text
    vals = r.json()["values"]
    assert vals["iso"] == fake_camera.get_config("iso").value and "capturetarget" not in vals
    r = await connected_client.post(f"{P}/from-camera", json={"name": "Two", "names": ["iso"]})
    assert list(r.json()["values"]) == ["iso"]
    r = await connected_client.post(f"{P}/from-camera", json={"name": "T", "names": ["datetime"]})
    assert r.status_code == 403


async def test_export_import_round_trip(client: httpx.AsyncClient) -> None:
    await make(client)
    b = await make(
        client,
        {"kind": "bracket", "name": "mine", "bracketing": {"mode": "quick", "iso": ["100", "400"]}},
    )
    doc = (await client.get(f"{P}/export")).json()
    assert doc["schema_version"] == 1 and len(doc["presets"]) == 2  # no built-ins
    for i in (b["id"],):
        await client.delete(f"{P}/{i}")
    # merge: existing name skipped, missing one created
    doc["presets"].append({"kind": "settings", "name": "broken", "values": {"nope": 1}})
    r = await client.post(f"{P}/import", json={"presets": doc["presets"]})
    res = r.json()
    assert (res["created"], res["skipped"], res["failed"]) == (1, 1, 1)
    assert [i["status"] for i in res["items"]] == ["skipped", "created", "error"]
    # replace
    r = await client.post(f"{P}/import", json={"replace": True, "presets": doc["presets"][:1]})
    assert r.json()["created"] == 1
    assert len((await client.get(P, params={"kind": "settings"})).json()["items"]) == 1
    assert (await client.get(P, params={"kind": "bracket"})).json()["items"][-1]["builtin"]


async def test_import_bad_item_does_not_reject_document(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{P}/import", json={"presets": [{"kind": "x"}, "junk"]})
    assert r.status_code == 422  # non-object item is a malformed document
    r = await client.post(f"{P}/import", json={"presets": [{"kind": "x"}]})
    assert r.status_code == 200 and r.json()["failed"] == 1


async def test_corrupt_file_tolerated_via_api(
    app: FastAPI, tmp_dirs: Any, client: httpx.AsyncClient
) -> None:
    (tmp_dirs.data_dir / FILE_NAME).write_text("garbage")
    r = await client.get(P)
    assert r.status_code == 200 and r.json()["warning"]
    await make(client)
    assert json.loads((tmp_dirs.data_dir / FILE_NAME).read_text())["presets"]
