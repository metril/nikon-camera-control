"""Regressions from the services/api review (bracket/bulb without a target, config patch, files)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.core.errors import NoTargetError
from tests.api import test_bracket_capture as br
from tests.api import test_bulb as bu


def _no_target(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise NoTargetError("No storage target is selected.")

    monkeypatch.setattr(app.state.storage, "root", boom)


BRACKET = {"mode": "steps", "steps": [{"settings": {"iso": "100"}}, {"settings": {"iso": "200"}}]}


@pytest.mark.parametrize("download", [False, True])
async def test_bracket_without_target_never_holds_the_lease(
    app: FastAPI,
    connected_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    download: bool,
) -> None:
    c = connected_client
    br.install(app)
    _no_target(app, monkeypatch)
    r = await c.post(br.P, json={"bracketing": BRACKET, "download": download})
    assert r.status_code == 202, r.text
    j = await br.wait_job(c, r.json()["id"])
    assert j["status"] == ("failed" if download else "completed"), j
    assert app.state.camera_service.status().leased_by is None


async def test_bulb_without_download_needs_no_target(
    app: FastAPI, connected_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = connected_client
    bu.install(app)
    _no_target(app, monkeypatch)
    r = await c.post(bu.B, json={"seconds": 2, "download": False})
    assert r.status_code == 202, r.text
    j = await bu.wait_job(c, r.json()["id"])
    assert j["status"] == "completed", j
    assert j["result"]["files"] == [] and j["result"]["camera_files"]


async def test_config_patch_cannot_touch_storage_targets(client: httpx.AsyncClient) -> None:
    for body in (
        {"storage": {"target_id": "usb-x"}},
        {"storage": {"backup_ids": ["usb-x"]}},
        {"storage": {"locations": []}},
    ):
        assert (await client.patch("/api/v1/config", json=body)).status_code == 422
    r = await client.patch("/api/v1/config", json={"storage": {"backup_interval_min": 30}})
    assert r.status_code == 200, r.text


async def test_files_photos_filter_is_image_plus_raw(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    o = app.state.storage.root()
    for n in ("a.jpg", "b.NEF", "c.mp4"):
        (o / n).write_bytes(b"x")
    r = (await client.get("/api/v1/files", params={"kind": "photos"})).json()
    assert r["total"] == 2 and {f["name"] for f in r["items"]} == {"a.jpg", "b.NEF"}
