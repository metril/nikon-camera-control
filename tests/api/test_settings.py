import httpx
from fastapi import FastAPI

from backend.camera.fake import FakeCamera
from backend.core.errors import CameraOperationFailed

S = "/api/v1/settings"


async def test_not_connected(client: httpx.AsyncClient) -> None:
    for r in (await client.get(S), await client.put(f"{S}/iso", json={"value": "400"})):
        assert r.status_code == 503 and r.json()["error"]["code"] == "CAMERA_NOT_CONNECTED"


async def test_list_common_and_all(connected_client: httpx.AsyncClient) -> None:
    common = (await connected_client.get(S)).json()
    names = [s["name"] for s in common]
    assert names[:2] == ["iso", "f-number"] and "datetime" not in names
    ap = next(s for s in common if s["name"] == "f-number")
    assert ap["alias"] == "aperture" and ap["writable"] and "f/5.6" in ap["choices"]
    assert not next(s for s in common if s["name"] == "capturetarget")["writable"]
    assert all(not s["writable"] or not s["readonly"] for s in common)
    allv = (await connected_client.get(S, params={"group": "all"})).json()
    assert {"datetime", "serialnumber", "manualfocusdrive"} <= {s["name"] for s in allv}
    mf = next(s for s in allv if s["name"] == "manualfocusdrive")
    assert mf["range"] == {"min": -1000, "max": 1000, "step": 1}
    assert (await connected_client.get(S, params={"group": "x"})).status_code == 422


async def test_repeated_reads_do_not_hit_backend_regression(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await connected_client.get(S)
    before = dict(fake_camera.calls)
    for _ in range(3):
        await connected_client.get(S)
        await connected_client.get(S, params={"group": "all"})
        await connected_client.get(f"{S}/iso")
    assert fake_camera.calls == before


async def test_get_by_alias_and_name(connected_client: httpx.AsyncClient) -> None:
    a = (await connected_client.get(f"{S}/aperture")).json()
    b = (await connected_client.get(f"{S}/f-number")).json()
    assert a == b and a["value"] == "f/5.6"
    r = await connected_client.get(f"{S}/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "SETTING_NOT_FOUND"


async def test_put_choice_and_event(app: FastAPI, connected_client: httpx.AsyncClient) -> None:
    sub = app.state.event_bus.subscribe()
    r = await connected_client.put(f"{S}/aperture", json={"value": "f/8"})
    assert r.status_code == 200 and r.json()["value"] == "f/8"
    assert (await connected_client.get(f"{S}/f-number")).json()["value"] == "f/8"
    ev = await anext(aiter(sub))
    assert ev.type == "setting_changed" and ev.data == {"name": "f-number", "value": "f/8"}
    r = await connected_client.put(f"{S}/iso", json={"value": 400})  # int -> choice "400"
    assert r.json()["value"] == "400"
    sub.close()


async def test_put_invalid_values(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    bad = [
        ("iso", "999999"),
        ("iso", True),
        ("whitebalance", "Nope"),
        ("f-number", 6.5),
        ("exposurecompensation", "+9"),
    ]
    for name, val in bad:
        r = await connected_client.put(f"{S}/{name}", json={"value": val})
        assert r.status_code == 422 and r.json()["error"]["code"] == "SETTING_INVALID", name
    assert fake_camera.calls.get("set_config", 0) == 0  # rejected before the camera


async def test_put_not_allowed_regression(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    cases = {
        "capturetarget": "Internal RAM",
        "datetime": 1700000000,
        "viewfinder": True,
        "autofocusdrive": True,
        "manualfocusdrive": 5,
        "bulb": True,
        "movie": True,
        "serialnumber": "x",  # readonly
    }
    for name, val in cases.items():
        r = await connected_client.put(f"{S}/{name}", json={"value": val})
        assert r.status_code == 403 and r.json()["error"]["code"] == "SETTING_NOT_ALLOWED", name
    assert fake_camera.calls.get("set_config", 0) == 0


async def test_patch_all_or_nothing_validation(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    r = await connected_client.patch(S, json={"values": {"iso": "400", "whitebalance": "Bogus"}})
    assert r.status_code == 422
    assert fake_camera.calls.get("set_config", 0) == 0
    assert (await connected_client.get(f"{S}/iso")).json()["value"] == "100"


async def test_patch_applies_in_stable_order(connected_client: httpx.AsyncClient) -> None:
    r = await connected_client.patch(
        S,
        json={
            "values": {"iso": "800", "aperture": "f/11", "autoexposuremode": "Aperture Priority"}
        },
    )
    assert r.status_code == 200
    assert [x["name"] for x in r.json()["results"]] == ["autoexposuremode", "f-number", "iso"]
    assert (await connected_client.get(f"{S}/iso")).json()["value"] == "800"


async def test_patch_midway_failure_reports_applied(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await connected_client.get(S)
    fake_camera.fail_next("set_config", 1, exc=CameraOperationFailed("boom"))
    r = await connected_client.patch(S, json={"values": {"focusmode": "AF-C", "iso": "400"}})
    assert r.status_code >= 500
    d = r.json()["error"]["details"]
    assert d["applied"] == [] and d["failed"] == "focusmode"


async def test_lease_blocks_writes_without_owner(
    app: FastAPI, connected_client: httpx.AsyncClient
) -> None:
    async with app.state.camera_service.lease("x"):
        r = await connected_client.put(f"{S}/iso", json={"value": "400"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "CAMERA_BUSY"
        assert (await connected_client.get(f"{S}/iso")).status_code == 200  # reads allowed


async def test_refresh_settings_route_rereads_tree(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await connected_client.get(S)
    n = fake_camera.calls["list_config"]
    r = await connected_client.post(f"{S}/refresh")
    assert r.status_code == 200 and fake_camera.calls["list_config"] == n + 1


async def test_fresh_get_rereads_one_widget_and_announces_change(
    app: FastAPI, connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    await connected_client.get(S)
    fake_camera._values["iso"] = "800"  # changed on the body, no event
    before = fake_camera.calls.get("list_config", 0)
    r = await connected_client.get(f"{S}/iso", params={"fresh": "true"})
    assert r.json()["value"] == "800"
    assert fake_camera.calls.get("list_config", 0) == before
    assert (await connected_client.get(f"{S}/iso")).json()["value"] == "800"
