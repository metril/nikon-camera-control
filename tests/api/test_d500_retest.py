"""Backend bugs found by the second real-D500 retest, each emulated by a FakeCamera option."""

import httpx
import pytest
from fastapi import FastAPI

from backend.camera.fake import FakeCamera

F = "/api/v1/camera/files"  # noqa: E501
P = "/api/v1/presets"


@pytest.fixture
def fake_camera() -> FakeCamera:
    return FakeCamera(d500_names=True, ram_info_fails=True, slot2_mirror=True)


async def test_root_listing_skips_unreadable_ram_files(
    connected_client: httpx.AsyncClient, app: FastAPI
) -> None:
    svc = app.state.camera_service
    await svc.set_setting("capturetarget", "Internal RAM")
    await svc.capture()
    r = await connected_client.get(F)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []  # the unreadable RAM entries are skipped, not a 502
    r = await connected_client.get("/api/v1/camera/folders")
    assert [f["name"] for f in r.json()["folders"]] == ["store_00010001", "store_00020001"]


async def test_from_camera_stores_logical_names_and_applies(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    r = await connected_client.post(f"{P}/from-camera", json={"name": "Now"})
    assert r.status_code == 201, r.text
    vals = r.json()["values"]
    assert "meteringmode" in vals and "autoexposuremode" in vals
    assert "exposuremetermode" not in vals and "expprogram" not in vals
    fake_camera.set_config("exposuremetermode", "Spot")
    r = await connected_client.post(f"{P}/{r.json()['id']}/apply")
    assert r.status_code == 200, r.text
    assert fake_camera.get_config("exposuremetermode").value == "Matrix"
    # camera-resolved names are accepted too and stored under the logical name
    r = await connected_client.post(
        f"{P}/from-camera", json={"name": "Two", "names": ["exposuremetermode"]}
    )
    assert r.status_code == 201 and list(r.json()["values"]) == ["meteringmode"]


async def test_capture_refused_on_bulb_shutter(
    connected_client: httpx.AsyncClient, fake_camera: FakeCamera
) -> None:
    fake_camera.set_config("shutterspeed", "Bulb")
    r = await connected_client.post("/api/v1/capture", json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["message"] == (
        "The shutter speed is set to Bulb. Choose a shutter speed, or use the Bulb capture mode."
    )
    assert fake_camera.calls.get("capture", 0) == 0
    assert (await connected_client.get("/api/v1/camera")).json()["state"] == "idle"
