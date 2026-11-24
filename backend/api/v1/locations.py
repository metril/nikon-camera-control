"""Storage locations, target, backups, offload and verification."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from backend.api.deps import ConfigStoreDep, JobManagerDep, StorageDep
from backend.api.errors import ERROR_RESPONSES
from backend.api.schemas.common import Ok
from backend.api.schemas.jobs import JobOut
from backend.api.schemas.locations import (
    BackupsSet,
    BackupStatusOut,
    FsckResult,
    LocationCreate,
    LocationOut,
    LocationsOut,
    LocationUpdate,
    OffloadRequest,
    SmbTest,
    SmbTestResult,
    TargetSet,
    VerifyRequest,
)
from backend.api.v1.sessions import SessionsDep
from backend.core.errors import InvalidState, PathNotAllowed
from backend.core.jobs import JobContext
from backend.core.security import require_api_key
from backend.services import integrity
from backend.services.backup import BackupService, dest_lock, offload_files, select_files
from backend.services.locations import LocationInfo, LocationService
from backend.services.storage import safe_join

router = APIRouter(
    tags=["storage"],
    dependencies=[Depends(require_api_key)],
    responses=ERROR_RESPONSES,
)

RESULT_LIST_CAP = 200
OFFLOAD_MIN_AGE_S = 10.0  # files modified more recently may still be written


def get_backup(request: Request) -> BackupService:
    return request.app.state.backup  # type: ignore[no-any-return,unused-ignore]


BackupDep = Annotated[BackupService, Depends(get_backup)]


def _out(i: LocationInfo) -> LocationOut:
    return LocationOut.model_validate(asdict(i))


def _all(svc: LocationService, store: ConfigStoreDep) -> LocationsOut:
    cfg = store.config.storage
    return LocationsOut(
        locations=[_out(i) for i in svc.list_locations()],
        target_id=cfg.target_id,
        backup_ids=cfg.backup_ids,
    )


@router.get("/locations", operation_id="list_locations", response_model=LocationsOut)
async def list_locations(svc: StorageDep, store: ConfigStoreDep) -> LocationsOut:
    return _all(svc, store)


@router.post("/locations", operation_id="add_location", response_model=LocationOut, status_code=201)
async def add_location(body: LocationCreate, svc: StorageDep) -> LocationOut:
    return _out(svc.add(**body.model_dump()))


@router.patch(
    "/locations/{location_id}", operation_id="update_location", response_model=LocationOut
)
async def update_location(location_id: str, body: LocationUpdate, svc: StorageDep) -> LocationOut:
    changes = body.model_dump(exclude_unset=True, exclude={"password"})
    return _out(svc.update(location_id, changes, password=body.password))


@router.delete("/locations/{location_id}", operation_id="delete_location", response_model=Ok)
async def delete_location(location_id: str, svc: StorageDep) -> Ok:
    await svc.remove(location_id)
    return Ok()


@router.post(
    "/locations/{location_id}/mount", operation_id="mount_location", response_model=LocationOut
)
async def mount_location(location_id: str, svc: StorageDep) -> LocationOut:
    return _out(await svc.mount(location_id))


@router.post(
    "/locations/{location_id}/unmount", operation_id="unmount_location", response_model=LocationOut
)
async def unmount_location(location_id: str, svc: StorageDep) -> LocationOut:
    await svc.unmount(location_id)
    return _out(svc.get(location_id))


@router.post(
    "/locations/{location_id}/fsck", operation_id="check_location", response_model=FsckResult
)
async def check_location(location_id: str, svc: StorageDep) -> FsckResult:
    rc, out = await svc.fsck(location_id)
    return FsckResult(returncode=rc, output=out)


@router.post("/locations/test-smb", operation_id="test_smb_location", response_model=SmbTestResult)
async def test_smb_location(body: SmbTest, svc: StorageDep) -> SmbTestResult:
    ok, msg = await svc.test_smb(body.unc, body.username, body.password, body.domain)
    return SmbTestResult(ok=ok, message=msg)


@router.put("/storage/target", operation_id="set_storage_target", response_model=LocationsOut)
async def set_storage_target(
    body: TargetSet, svc: StorageDep, store: ConfigStoreDep
) -> LocationsOut:
    svc.set_target(body.id)
    return _all(svc, store)


@router.put("/storage/backups", operation_id="set_storage_backups", response_model=LocationsOut)
async def set_storage_backups(
    body: BackupsSet, svc: StorageDep, store: ConfigStoreDep
) -> LocationsOut:
    svc.set_backups(body.ids)
    return _all(svc, store)


def _status(backup: BackupService, store: ConfigStoreDep) -> BackupStatusOut:
    return BackupStatusOut(**asdict(backup.status), backup_ids=store.config.storage.backup_ids)


@router.get("/backup/status", operation_id="get_backup_status", response_model=BackupStatusOut)
async def get_backup_status(backup: BackupDep, store: ConfigStoreDep) -> BackupStatusOut:
    return _status(backup, store)


@router.post(
    "/backup/run", operation_id="run_backup", response_model=BackupStatusOut, status_code=202
)
async def run_backup(backup: BackupDep, store: ConfigStoreDep) -> BackupStatusOut:
    """Start a sync now (a run in progress is repeated once it ends)."""
    backup.run_now()
    return _status(backup, store)


def _root_of(svc: LocationService, location_id: str) -> Path:
    root = svc.root_of(location_id)
    if root is None:
        raise InvalidState("The location is not mounted", details={"id": location_id})
    return root


def _progress(loop: asyncio.AbstractEventLoop, ctx: JobContext, text: str) -> Any:
    def report(done: int, total: int) -> None:
        loop.call_soon_threadsafe(
            ctx.report, done / total if total else 0.0, f"{text} {done}/{total}"
        )

    return report


@router.post("/offload", operation_id="start_offload", response_model=JobOut, status_code=202)
async def start_offload(
    body: OffloadRequest,
    svc: StorageDep,
    store: ConfigStoreDep,
    jobs: JobManagerDep,
    sessions: SessionsDep,
) -> JobOut:
    """Verified copy of files from one mounted location to another, then delete the source
    files (unless ``keep_source``) once the copy re-hashed equal. Files of running, paused or
    render-held sessions and files modified in the last 10 seconds are skipped."""
    if body.from_id == body.to_id:
        raise InvalidState("Source and destination must differ")
    src, dst = _root_of(svc, body.from_id), _root_of(svc, body.to_id)
    sc = body.scope
    in_use: frozenset[str] = frozenset()
    if body.from_id == svc.target_id:  # sessions live on the target only
        in_use = await sessions.in_use_ids()
        if sc.kind == "session" and sc.session_id in in_use:
            raise InvalidState(
                "This session is active or being rendered", details={"session_id": sc.session_id}
            )
    try:
        files = await asyncio.to_thread(
            lambda: select_files(
                src,
                sc.kind,
                session_id=sc.session_id,
                before=sc.before,
                exclude_sessions=in_use,
                min_age_s=OFFLOAD_MIN_AGE_S,
            )
        )
    except ValueError as exc:
        raise PathNotAllowed(str(exc)) from exc
    sidecars = store.config.storage.sidecars
    loop = asyncio.get_running_loop()

    async def run(ctx: JobContext) -> dict[str, Any]:
        cancel = threading.Event()
        try:
            async with dest_lock(dst):
                rep = await asyncio.to_thread(
                    offload_files,
                    files,
                    src,
                    dst,
                    keep_source=body.keep_source,
                    sidecars=sidecars,
                    cancel=cancel,
                    progress=_progress(loop, ctx, "Offloading"),
                )
        except asyncio.CancelledError:
            cancel.set()
            raise
        return {
            "total": len(files),
            "copied": rep.copied,
            "skipped": rep.skipped,
            "deleted_source": rep.deleted_source,
            "failed": [f"{p}: {m}" for p, m in rep.failed[:RESULT_LIST_CAP]],
            "failed_count": len(rep.failed),
            "cancelled": rep.cancelled,
        }

    return JobOut.model_validate(jobs.submit("offload", run, exclusive_key="offload").model_dump())


@router.post("/verify", operation_id="start_verify", response_model=JobOut, status_code=202)
async def start_verify(body: VerifyRequest, svc: StorageDep, jobs: JobManagerDep) -> JobOut:
    """Re-hash a location's files against its own SHA256SUMS (job result: ok, mismatched,
    missing and unlisted counts and lists)."""
    lid = body.location_id or svc.target_id
    root = _root_of(svc, lid) if lid else svc.root()
    sub = body.folder.strip("/")
    if sub:
        safe_join(root, sub)  # rejects traversal
    loop = asyncio.get_running_loop()

    async def run(ctx: JobContext) -> dict[str, Any]:
        cancel = threading.Event()

        def progress(n: int) -> None:
            loop.call_soon_threadsafe(ctx.report, 0.0, f"Checked {n} files")

        try:
            rep = await asyncio.to_thread(
                integrity.verify, root, sub, cancel=cancel, progress=progress
            )
        except asyncio.CancelledError:
            cancel.set()
            raise
        return {
            "location_id": lid,
            "checked": rep.checked,
            "ok": rep.ok,
            "mismatched": rep.mismatched[:RESULT_LIST_CAP],
            "mismatched_count": len(rep.mismatched),
            "missing": rep.missing[:RESULT_LIST_CAP],
            "missing_count": len(rep.missing),
            "unlisted": rep.unlisted[:RESULT_LIST_CAP],
            "unlisted_count": len(rep.unlisted),
            "cancelled": rep.cancelled,
        }

    return JobOut.model_validate(jobs.submit("verify", run, exclusive_key="verify").model_dump())
