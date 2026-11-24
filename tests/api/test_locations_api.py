import asyncio
import json
import os
import stat
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter

from backend.api.schemas.events import TypedEvent
from backend.app import create_app
from backend.camera.fake import FakeCamera
from backend.core.config_store import AppConfig, ConfigStore
from tests.fake_helper import FakeHelper

V = "/api/v1"
UUID = "ABCD-1234"
UID = f"usb-{UUID}"
PW = "s3cr3t-" + "pass"


@dataclass
class Env:
    app: FastAPI
    c: httpx.AsyncClient
    helper: FakeHelper
    root: Path  # tmp_path


@pytest.fixture
async def env(tmp_path: Path, app_config: AppConfig, fake_camera: FakeCamera) -> AsyncIterator[Env]:
    helper = FakeHelper(tmp_path)
    store = ConfigStore(tmp_path / "data" / "config.json", initial=app_config)
    app = create_app(
        config_store=store,
        data_dir=tmp_path / "data",
        location_options={
            "runner": helper.runner,
            "mount_base": helper.base,
            "mountinfo": helper.mountinfo,
            "ismount": helper.ismount,
            "poll_interval_s": 3600.0,
        },
        backend_factory=lambda: fake_camera,
        auto_connect=False,
        event_quiet_window_s=0.02,
        disconnect_wait_s=0.5,
    )
    async with app.router.lifespan_context(app):
        await app.state.camera_service.connect()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield Env(app, c, helper, tmp_path)


async def _wait_job(c: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
    for _ in range(300):
        j = (await c.get(f"{V}/jobs/{job_id}")).json()
        if j["status"] in ("completed", "failed", "cancelled"):
            return j  # type: ignore[no-any-return]
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish")


async def _setup_target(e: Env, uuid: str = UUID) -> str:
    e.helper.plug(uuid)
    r = await e.c.post(f"{V}/locations", json={"kind": "usb", "uuid": uuid, "name": "SSD"})
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    await e.app.state.storage.refresh()  # detect + auto-mount
    assert (await e.c.put(f"{V}/storage/target", json={"id": lid})).status_code == 200
    return lid


def _age(root: Path) -> None:
    t = time.time() - 120
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (t, t))


async def test_everything_409s_without_a_target(env: Env) -> None:
    for method, url in [
        ("post", f"{V}/capture"),
        ("get", f"{V}/files"),
        ("get", f"{V}/sessions"),
        ("post", f"{V}/capture/bulb"),
    ]:
        kw: dict[str, Any] = {"json": {"seconds": 5} if url.endswith("bulb") else {}}
        if method == "get":
            kw = {}
        r = await getattr(env.c, method)(url, **kw)
        assert r.status_code == 409, (url, r.text)
    r = await env.c.post(f"{V}/capture", json={})
    assert r.json()["error"]["code"] == "NO_TARGET"
    assert (await env.c.get(f"{V}/info")).json()["output_free_bytes"] is None
    # nothing was shot or written
    assert not list(env.root.rglob("*.JPG"))


async def test_capture_lands_on_target_with_hashes(env: Env) -> None:
    lid = await _setup_target(env)
    r = await env.c.post(f"{V}/capture", json={})
    assert r.status_code == 200, r.text
    f = r.json()["files"][0]
    target = env.helper.base / lid
    shot = target / f["path"]
    assert shot.is_file()
    import hashlib

    digest = hashlib.sha256(shot.read_bytes()).hexdigest()
    assert (target / "SHA256SUMS").read_text() == f"{digest}  {shot.name}\n"
    assert (target / f"{shot.name}.sha256").read_text() == f"{digest}  {shot.name}\n"
    # nothing image-bearing outside the target (data dir holds config only)
    assert not [p for p in (env.root / "data").rglob("*") if p.suffix in (".jpg", ".JPG")]
    # thumbnail cache lives on the target
    assert (await env.c.get(f"{V}/files/{f['path']}/thumbnail")).status_code in (200, 404, 415)


async def test_gallery_hides_bookkeeping_files(env: Env) -> None:
    await _setup_target(env)
    await env.c.post(f"{V}/capture", json={})
    names = [i["name"] for i in (await env.c.get(f"{V}/files")).json()["items"]]
    assert len(names) == 1 and names[0].endswith(".JPG")


async def test_passwords_are_write_only(env: Env) -> None:
    r = await env.c.post(
        f"{V}/locations",
        json={"kind": "smb", "name": "NAS", "unc": "//nas/photos", "username": "u", "password": PW},
    )
    assert r.status_code == 201 and r.json()["has_password"] is True
    await env.c.patch(f"{V}/locations/smb-nas", json={"password": PW + "2"})
    bodies = [
        r.text,
        (await env.c.get(f"{V}/locations")).text,
        (await env.c.get(f"{V}/config")).text,
        (await env.c.get(f"{V}/info")).text,
        (env.root / "data" / "config.json").read_text(),
    ]
    assert all(PW not in b for b in bodies)
    secrets = env.root / "data" / "secrets.json"
    assert json.loads(secrets.read_text())["smb"]["smb-nas"] == PW + "2"
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o600
    assert "PW" not in (await env.c.get(f"{V}/locations")).text


async def test_smb_test_connection_endpoint(env: Env) -> None:
    r = await env.c.post(f"{V}/locations/test-smb", json={"unc": "//nas/x", "password": PW})
    assert r.json() == {"ok": True, "message": "ok"}
    env.helper.smb_up = False
    r = await env.c.post(f"{V}/locations/test-smb", json={"unc": "//nas/x"})
    assert r.json()["ok"] is False and PW not in r.text


async def test_validation_and_unknown_ids(env: Env) -> None:
    r = await env.c.post(f"{V}/locations", json={"kind": "smb", "unc": "nas/share"})
    assert r.status_code == 422
    r = await env.c.post(
        f"{V}/locations", json={"kind": "smb", "unc": "//nas/x", "username": "a\nb"}
    )
    assert r.status_code == 422
    assert (await env.c.put(f"{V}/storage/target", json={"id": "usb-nope"})).status_code == 404
    assert (await env.c.post(f"{V}/locations/usb-nope/mount")).status_code == 404


async def test_target_switch_refused_while_a_job_runs(env: Env) -> None:
    a = await _setup_target(env)
    env.helper.plug("2222-2222")
    await env.c.post(f"{V}/locations", json={"kind": "usb", "uuid": "2222-2222"})
    gate = asyncio.Event()

    async def hold(ctx: Any) -> dict[str, Any]:
        await gate.wait()
        return {}

    job = env.app.state.job_manager.submit("bulb", hold)
    r = await env.c.put(f"{V}/storage/target", json={"id": "usb-2222-2222"})
    assert r.status_code == 409
    r = await env.c.post(f"{V}/locations/{a}/unmount")
    assert r.status_code == 409
    gate.set()
    await _wait_job(env.c, job.id)
    assert (await env.c.put(f"{V}/storage/target", json={"id": "usb-2222-2222"})).status_code == 200


async def test_verify_job_reports_mismatch_missing_and_unlisted(env: Env) -> None:
    lid = await _setup_target(env)
    for _ in range(3):
        await env.c.post(f"{V}/capture", json={})
    target = env.helper.base / lid
    shots = sorted(target.glob("*.JPG"))
    assert len(shots) >= 2
    shots[0].write_bytes(b"corrupt")
    shots[1].unlink()
    (target / "hand-copied.JPG").write_bytes(b"x")
    r = await env.c.post(f"{V}/verify", json={})
    assert r.status_code == 202
    j = await _wait_job(env.c, r.json()["id"])
    assert j["status"] == "completed", j
    res = j["result"]
    assert res["mismatched"] == [shots[0].name]
    assert res["missing"] == [shots[1].name]
    assert res["unlisted"] == ["hand-copied.JPG"]
    assert res["ok"] == len(shots) - 2
    assert (await env.c.post(f"{V}/verify", json={"folder": "../x"})).status_code == 400


async def test_backup_follows_target_and_resumes_after_outage(env: Env) -> None:
    lid = await _setup_target(env)
    env.helper.smb_up = False
    env.helper.plug("2222-2222")
    r = await env.c.post(f"{V}/locations", json={"kind": "smb", "name": "NAS", "unc": "//nas/b"})
    bid = r.json()["id"]
    assert (await env.c.put(f"{V}/storage/backups", json={"ids": [bid]})).status_code == 200
    assert (await env.c.put(f"{V}/storage/backups", json={"ids": [lid]})).status_code == 409
    await env.app.state.storage.refresh()  # NAS is down: auto-mount fails
    await env.c.post(f"{V}/capture", json={})
    await env.c.post(f"{V}/capture", json={})
    r = await env.c.post(f"{V}/backup/run")
    assert r.status_code == 202
    await env.app.state.backup.wait_idle()
    st = (await env.c.get(f"{V}/backup/status")).json()
    assert st["backups_online"] == [] and st["backup_ids"] == [bid]
    # the NAS returns: coming online triggers a run that copies what is missing
    env.helper.smb_up = True
    env.app.state.backup._debounce = 0.01
    env.app.state.storage._rt[bid].retry_at = 0.0
    await env.app.state.storage.refresh()
    for _ in range(200):
        await asyncio.sleep(0.02)
        await env.app.state.backup.wait_idle()
        if list((env.helper.base / bid).glob("*.JPG")):
            break
    dest = env.helper.base / bid
    src = env.helper.base / lid
    assert sorted(p.name for p in dest.glob("*.JPG")) == sorted(p.name for p in src.glob("*.JPG"))
    assert (dest / "SHA256SUMS").read_text() == (src / "SHA256SUMS").read_text()
    st = (await env.c.get(f"{V}/backup/status")).json()
    assert st["running"] is False and st["failed"] == 0 and st["last_run"]


async def test_offload_moves_files_after_verification(env: Env) -> None:
    lid = await _setup_target(env)
    await env.c.post(f"{V}/locations", json={"kind": "smb", "name": "NAS", "unc": "//nas/b"})
    await env.app.state.storage.refresh()
    await env.c.post(f"{V}/capture", json={})
    src = env.helper.base / lid
    names = [p.name for p in src.glob("*.JPG")]
    _age(src)
    body = {"from_id": lid, "to_id": "smb-nas", "scope": {"kind": "all"}, "keep_source": True}
    j = await _wait_job(env.c, (await env.c.post(f"{V}/offload", json=body)).json()["id"])
    assert j["status"] == "completed" and j["result"]["copied"] == len(names)
    assert [p.name for p in src.glob("*.JPG")] == names  # kept
    body["keep_source"] = False
    j = await _wait_job(env.c, (await env.c.post(f"{V}/offload", json=body)).json()["id"])
    assert j["result"]["deleted_source"] == len(names)
    assert not list(src.glob("*.JPG")) and not (src / "SHA256SUMS").exists()
    assert sorted(p.name for p in (env.helper.base / "smb-nas").glob("*.JPG")) == sorted(names)
    r = await env.c.post(f"{V}/offload", json={**body, "to_id": lid})
    assert r.status_code == 409


async def test_events_are_typed(env: Env) -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(TypedEvent)
    async with env.app.state.event_bus.subscribe() as sub:
        await _setup_target(env)
        await env.app.state.backup.wait_idle()
        seen = {}
        await asyncio.sleep(0.05)
        for _ in range(50):
            try:
                ev = await asyncio.wait_for(sub.__anext__(), 0.05)
            except TimeoutError:
                break
            seen[ev.type.value] = ev
    assert "locations_changed" in seen
    for ev in seen.values():
        adapter.validate_python(ev.model_dump(mode="json"))


async def test_unplugged_drive_cuts_off_the_target(env: Env) -> None:
    lid = await _setup_target(env)
    env.helper.unplug(UUID)
    await env.app.state.storage.refresh()
    r = await env.c.post(f"{V}/capture", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_TARGET"
    assert lid in (await env.c.get(f"{V}/locations")).text


async def test_offload_skips_fresh_files_and_refuses_active_session(env: Env) -> None:
    lid = await _setup_target(env)
    await env.c.post(f"{V}/locations", json={"kind": "smb", "name": "NAS", "unc": "//nas/b"})
    await env.app.state.storage.refresh()
    await env.c.post(f"{V}/capture", json={})
    body = {"from_id": lid, "to_id": "smb-nas", "scope": {"kind": "all"}, "keep_source": False}
    j = await _wait_job(env.c, (await env.c.post(f"{V}/offload", json=body)).json()["id"])
    assert j["result"]["total"] == 0 and j["result"]["deleted_source"] == 0  # all fresh
    from backend.api.v1.sessions import build_sessions_service

    store = env.app.state.services.get("sessions", lambda: build_sessions_service(env.app.state))
    sid = "20250101-000000-abcd"
    with store.hold(sid):
        assert sid in await store.in_use_ids()
        r = await env.c.post(
            f"{V}/offload",
            json={**body, "scope": {"kind": "session", "session_id": sid}},
        )
    assert r.status_code == 409
