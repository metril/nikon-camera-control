"""Storage locations (USB drives, SMB shares), the capture target and mount lifecycle.

All mounting is done by the root helper ``ncc-storage`` through ``sudo -n`` behind an
injectable async runner. A location is a plain directory once mounted; the target is the one
location that receives captures. ``LocationService`` also implements ``StorageRoot`` so
services resolve the target directory dynamically (``NoTargetError`` when unavailable).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from backend.api.schemas.common import EventType
from backend.core.config_store import ConfigStore, StorageLocation
from backend.core.errors import (
    ConfigInvalid,
    FileTooLarge,
    InvalidState,
    LocationBusy,
    LocationNotFound,
    MountFailed,
    NoTargetError,
)
from backend.core.events import EventBus
from backend.core.secrets import SecretStore
from backend.core.storage_root import CACHE_DIRNAME, FAT32_MAX_FILE
from backend.services import integrity

log = logging.getLogger(__name__)

HELPER = "/usr/local/sbin/ncc-storage"
EXIT_BUSY = 16
PROBE_TIMEOUT_S = 5.0
FAT_TYPES = frozenset({"vfat", "fat", "msdos", "fat32"})

Runner = Callable[..., Awaitable[tuple[int, str, str]]]  # (args, stdin=None)
Listener = Callable[[str, str | None], None]


FSCK_TIMEOUT_S = 3600.0  # a repair of a big drive legitimately takes long
TERM_GRACE_S = 10.0
FORMAT_TIMEOUT_S = 3600.0
FORMAT_FS = ("exfat", "fat32", "ntfs", "ext4")
FORMAT_LABEL_MAX = {"exfat": 15, "fat32": 11, "ntfs": 32, "ext4": 16}
_LABEL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ -]*$")
LIVE_MOUNT_TTL_S = 0.25  # how long root_of() trusts its last read of the mount table


async def sudo_runner(
    args: Sequence[str], stdin: str | None = None, limit_s: float = 180.0
) -> tuple[int, str, str]:
    """Run the helper as root via sudo (the only privileged operation the app performs).
    ``stdin`` carries secrets (SMB credentials); they never touch the filesystem.
    On timeout/cancel sudo gets SIGTERM, which it relays to the helper (a SIGKILL of sudo
    would orphan the root process), and is killed only if it ignores that."""
    proc = await asyncio.create_subprocess_exec(
        "sudo",
        "-n",
        HELPER,
        *args,
        stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(None if stdin is None else stdin.encode()), timeout=limit_s
        )
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), TERM_GRACE_S)
            except (TimeoutError, asyncio.CancelledError):
                proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(proc.wait()), TERM_GRACE_S)  # reap
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


FAT32_MAX_BYTES = 4294965248 * 512  # 2 TiB less 1 MiB; the helper refuses larger disks too


def fat32_error(fstype: str, size: int) -> str | None:
    if fstype == "fat32" and size > FAT32_MAX_BYTES:
        return "Use exFAT for drives over 2 TB"
    return None


def label_error(fstype: str, label: str) -> str | None:
    """Why ``label`` cannot label a ``fstype`` volume, or None. ASCII letters, digits, space,
    ``_`` and ``-`` are safe on every filesystem (FAT stores them uppercase)."""
    if fstype not in FORMAT_LABEL_MAX:
        return f"Unsupported filesystem: {fstype}"
    limit = FORMAT_LABEL_MAX[fstype]
    if len(label) > limit:
        return f"The label can have at most {limit} characters for {fstype}"
    if label and not _LABEL_RE.fullmatch(label):
        return (
            "The label may only use letters, digits, spaces, '_' and '-', "
            "and must not start with '-' or a space"
        )
    return None


def parse_mountinfo(text: str) -> set[str]:
    """Mount points listed in /proc/self/mountinfo (octal escapes decoded)."""
    points: set[str] = set()
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) > 4:
            points.add(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4]))
    return points


@dataclass
class _Runtime:
    present: bool = False
    mounted: bool = False
    root: Path | None = None
    fstype: str | None = None
    size: int | None = None
    free: int | None = None
    label: str | None = None
    supported: bool = True
    reason: str | None = None
    error: str | None = None
    user_unmounted: bool = False
    retry_at: float = 0.0
    backoff: float = 2.0
    encrypted: bool | None = None


@dataclass(frozen=True)
class LocationInfo:
    id: str
    kind: Literal["usb", "smb"]
    name: str
    uuid: str | None
    unc: str | None
    username: str | None
    domain: str | None
    auto_mount: bool
    configured: bool
    present: bool
    mounted: bool
    supported: bool
    reason: str | None
    fstype: str | None
    label: str | None
    size: int | None
    free: int | None
    error: str | None
    has_password: bool
    is_target: bool
    is_backup: bool
    encrypted: bool | None = None
    disk: dict[str, Any] | None = None  # physical disk: name, majmin, size, model, diskseq


class _ProbePending(Exception):
    """The previous probe of the same location has not finished (hung mount)."""


@dataclass
class _Detected:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    ok: bool = False


class LocationService:
    def __init__(
        self,
        store: ConfigStore,
        secrets: SecretStore,
        bus: EventBus,
        *,
        runner: Runner = sudo_runner,
        mount_base: Path = Path("/mnt/loc"),
        mountinfo: Path = Path("/proc/self/mountinfo"),
        busy: Callable[[], bool] = lambda: False,
        poll_interval_s: float = 3.0,
        fixed_target: Path | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._bus = bus
        self._run = runner
        self._base = Path(mount_base)
        self._mountinfo = Path(mountinfo)
        self._points: set[str] = set()  # mount points seen by the last live read / mount / unmount
        self._live_at = float("-inf")
        self._fsck_busy: set[str] = set()
        self._format_busy: set[str] = set()  # physical disk names being formatted
        self.busy = busy
        self._poll = poll_interval_s
        self._fixed = Path(fixed_target) if fixed_target is not None else None
        self._rt: dict[str, _Runtime] = {}
        self._gen: dict[str, int] = {}  # bumped on every new mount of a location
        self._probe_pool = ThreadPoolExecutor(2, thread_name_prefix="loc-probe")
        self._probes: dict[tuple[str, str], asyncio.Future[Any]] = {}
        self._detected = _Detected()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._listeners: list[Listener] = []
        self.on_stored: Callable[[], None] | None = None

    # ---- StorageRoot --------------------------------------------------------------------
    @property
    def target_id(self) -> str | None:
        return "fixed" if self._fixed is not None else self._store.config.storage.target_id

    def housekeeping_key(self) -> tuple[str, int] | None:
        """(target id, mount generation): changes only when the target actually changes
        or is mounted anew."""
        tid = self.target_id
        return None if tid is None else (tid, self._gen.get(tid, 0))

    def mount_point(self, location_id: str) -> Path:
        return self._base / location_id

    def root_of(self, location_id: str) -> Path | None:
        """Mounted, guarded root of a location, or None."""
        rt = self._rt.get(location_id)
        if rt is None or not rt.mounted or rt.root is None:
            return None
        if str(self.mount_point(location_id)) not in self._live_points():
            return None
        return rt.root

    def _live_points(self) -> set[str]:
        """Mount table read straight from mountinfo (a procfs read: never touches the mounts,
        so a dead SMB share cannot hang it), cached for a fraction of a second. Catches a
        vanished mount before the next poll so writes never land in the bare mount dir."""
        now = time.monotonic()
        if now - self._live_at >= LIVE_MOUNT_TTL_S:
            self._points, self._live_at = self._mounted_points(), now
        return self._points

    def root(self) -> Path:
        if self._fixed is not None:
            return self._fixed
        tid = self._store.config.storage.target_id
        if tid is None:
            raise NoTargetError("No storage target is selected. Choose one in Settings.")
        root = self.root_of(tid)
        if root is None:
            raise NoTargetError("The storage target is not mounted.")
        return root

    target_dir = root

    def cache(self) -> Path:
        return self.root() / CACHE_DIRNAME

    def source(self) -> tuple[str, Path] | None:
        try:
            return (self.target_id or "", self.root())
        except NoTargetError:
            return None

    def destinations(self) -> list[tuple[str, Path]]:
        if self._fixed is not None:
            return []
        cfg = self._store.config.storage
        out = []
        for bid in cfg.backup_ids:
            root = self.root_of(bid)
            if root is not None and bid != cfg.target_id:
                out.append((bid, root))
        return out

    def _target_fstype(self) -> str | None:
        tid = self._store.config.storage.target_id
        rt = self._rt.get(tid) if tid else None
        return rt.fstype if rt else None

    def check_file_size(self, size: int | None) -> None:
        fs = self._target_fstype()
        if size is not None and fs in FAT_TYPES and size > FAT32_MAX_FILE:
            raise FileTooLarge(
                f"This file is {size} bytes; the target is FAT32 (4 GiB limit). "
                "Use an exFAT or ext4 target."
            )

    def stored(self, path: Path) -> None:
        """A file was finalized on the target (blocking): record its hash, queue a backup."""
        if self._fixed is not None:
            return
        try:
            integrity.record(path, sidecar=self._store.config.storage.sidecars)
        except Exception:
            log.exception("could not record hash of %s", path)
        if self.on_stored is not None:
            self.on_stored()

    # ---- events -------------------------------------------------------------------------
    def subscribe(self, cb: Listener) -> None:
        self._listeners.append(cb)

    def _changed(self, reason: str, location_id: str | None = None) -> None:
        self._bus.publish(
            EventType.LOCATIONS_CHANGED,
            {
                "reason": reason,
                "id": location_id,
                "target_id": self._store.config.storage.target_id,
            },
        )
        for cb in list(self._listeners):
            try:
                cb(reason, location_id)
            except Exception:
                log.exception("location listener failed")

    # ---- registry -----------------------------------------------------------------------
    def _cfg(self, location_id: str) -> StorageLocation:
        for loc in self._store.config.storage.locations:
            if loc.id == location_id:
                return loc
        raise LocationNotFound(details={"id": location_id})

    def _state(self, location_id: str) -> _Runtime:
        return self._rt.setdefault(location_id, _Runtime())

    def _info(self, loc: StorageLocation) -> LocationInfo:
        rt = self._state(loc.id)
        cfg = self._store.config.storage
        return LocationInfo(
            id=loc.id,
            kind=loc.kind,
            name=loc.name or rt.label or loc.id,
            uuid=loc.uuid,
            unc=loc.unc,
            username=loc.username,
            domain=loc.domain,
            auto_mount=loc.auto_mount,
            configured=True,
            present=rt.present if loc.kind == "usb" else rt.mounted or rt.error is None,
            mounted=rt.mounted,
            supported=rt.supported,
            reason=rt.reason,
            fstype=rt.fstype,
            label=rt.label,
            size=rt.size,
            free=rt.free,
            error=rt.error,
            has_password=loc.kind == "smb" and self._secrets.has_smb(loc.id),
            is_target=loc.id == cfg.target_id,
            is_backup=loc.id in cfg.backup_ids,
            encrypted=rt.encrypted if rt.mounted else None,
            disk=self._disk_ref(self._detected.items.get(loc.uuid or ""))
            if loc.kind == "usb"
            else None,
        )

    def list_locations(self) -> list[LocationInfo]:
        cfg = self._store.config.storage
        out = [self._info(loc) for loc in cfg.locations]
        known = {loc.uuid for loc in cfg.locations if loc.uuid}
        for item in self._detected.items.values():
            if item.get("uuid") in known:
                continue
            uuid = item.get("uuid")
            out.append(
                LocationInfo(
                    id=f"usb-{uuid}" if uuid else f"dev-{item.get('name')}",
                    kind="usb",
                    name=item.get("label") or item.get("name") or "USB drive",
                    uuid=uuid,
                    unc=None,
                    username=None,
                    domain=None,
                    auto_mount=False,
                    configured=False,
                    present=True,
                    mounted=bool(item.get("mounted")),
                    supported=bool(item.get("supported")) and bool(uuid),
                    reason=item.get("reason") or (None if uuid else "No filesystem UUID"),
                    fstype=item.get("fstype"),
                    label=item.get("label"),
                    size=item.get("size"),
                    free=None,
                    error=None,
                    has_password=False,
                    is_target=False,
                    is_backup=False,
                    disk=self._disk_ref(item),
                )
            )
        return out

    @staticmethod
    def _disk_ref(item: dict[str, Any] | None) -> dict[str, Any] | None:
        d = item.get("disk") if item else None
        return dict(d) if isinstance(d, dict) and d.get("name") else None

    def get(self, location_id: str) -> LocationInfo:
        for info in self.list_locations():
            if info.id == location_id:
                return info
        raise LocationNotFound(details={"id": location_id})

    # ---- configuration changes ----------------------------------------------------------
    def _save_locations(self, locs: list[StorageLocation], **extra: Any) -> None:
        patch: dict[str, Any] = {"locations": [loc.model_dump(mode="json") for loc in locs]}
        patch.update(extra)
        self._store.update({"storage": patch})

    def add(
        self,
        *,
        kind: Literal["usb", "smb"],
        name: str = "",
        uuid: str | None = None,
        unc: str | None = None,
        username: str | None = None,
        domain: str | None = None,
        password: str | None = None,
        auto_mount: bool = True,
    ) -> LocationInfo:
        cfg = self._store.config.storage
        if kind == "usb":
            lid = f"usb-{uuid}"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", (name or (unc or "").rsplit("/", 1)[-1]).lower())
            slug = slug.strip("-")[:24] or "share"
            lid, n = f"smb-{slug}", 1
            ids = {loc.id for loc in cfg.locations}
            while lid in ids:
                n += 1
                lid = f"smb-{slug}-{n}"
        if any(loc.id == lid for loc in cfg.locations):
            raise InvalidState("This location is already registered", details={"id": lid})
        try:
            loc = StorageLocation(
                id=lid, kind=kind, name=name, uuid=uuid, unc=unc, username=username,
                domain=domain, auto_mount=auto_mount,
            )  # fmt: skip
        except ValueError as exc:
            raise ConfigInvalid(str(exc)) from exc
        if password:
            self._secrets.set_smb(lid, password)
        self._save_locations([*cfg.locations, loc])
        self._changed("added", lid)
        return self._info(loc)

    def update(
        self, location_id: str, changes: dict[str, Any], password: str | None = None
    ) -> LocationInfo:
        cfg = self._store.config.storage
        cur = self._cfg(location_id)
        merged = {**cur.model_dump(), **changes}
        try:
            new = StorageLocation.model_validate(merged)
        except ValueError as exc:
            raise ConfigInvalid(str(exc)) from exc
        if password is not None:
            self._secrets.set_smb(location_id, password or None)
        self._save_locations([new if loc.id == location_id else loc for loc in cfg.locations])
        self._changed("updated", location_id)
        return self._info(new)

    async def remove(self, location_id: str) -> None:
        self._cfg(location_id)
        if self._state(location_id).mounted:
            await self.unmount(location_id)
        cfg = self._store.config.storage  # after the await: the config may have changed meanwhile
        self._store.update(
            {
                "storage": {
                    "target_id": None if cfg.target_id == location_id else cfg.target_id,
                    "backup_ids": [b for b in cfg.backup_ids if b != location_id],
                    "locations": [
                        loc.model_dump(mode="json")
                        for loc in cfg.locations
                        if loc.id != location_id
                    ],
                }
            }
        )
        self._secrets.set_smb(location_id, None)
        self._rt.pop(location_id, None)
        self._changed("removed", location_id)

    def set_target(self, location_id: str | None) -> None:
        cfg = self._store.config.storage
        if location_id is not None:
            self._cfg(location_id)
            if location_id in cfg.backup_ids:
                raise InvalidState("This location is a backup; remove it from the backups first")
        if location_id == cfg.target_id:
            return  # unchanged: no event, no housekeeping
        if self.busy():
            raise InvalidState("Cannot switch the target while a capture or job is active")
        self._store.update({"storage": {"target_id": location_id}})
        self._changed("target", location_id)

    def set_backups(self, ids: list[str]) -> None:
        cfg = self._store.config.storage
        for i in ids:
            self._cfg(i)
        if cfg.target_id in ids:
            raise InvalidState("The target cannot also be a backup")
        self._store.update({"storage": {"backup_ids": list(dict.fromkeys(ids))}})
        self._changed("backups", None)

    # ---- mount / unmount ----------------------------------------------------------------
    @staticmethod
    def _item_location_id(item: dict[str, Any]) -> str:
        uuid = item.get("uuid")
        return f"usb-{uuid}" if uuid else f"dev-{item.get('name')}"

    def _disk_items(self, disk: str) -> list[dict[str, Any]]:
        return [
            i for i in self._detected.items.values() if (i.get("disk") or {}).get("name") == disk
        ]

    def _disk_of(self, location_id: str) -> str | None:
        for i in self._detected.items.values():
            if self._item_location_id(i) == location_id:
                return (i.get("disk") or {}).get("name")
        return None

    def _check_not_checking(self, location_id: str) -> None:
        if location_id in self._fsck_busy:
            raise LocationBusy("The drive is being checked", details={"id": location_id})
        if self._format_busy and self._disk_of(location_id) in self._format_busy:
            raise LocationBusy("The drive is being formatted", details={"id": location_id})

    async def mount(self, location_id: str, *, user: bool = True) -> LocationInfo:
        self._check_not_checking(location_id)
        async with self._lock:
            self._check_not_checking(location_id)  # a check may have started while we waited
            return await self._mount(location_id, user=user)

    async def _mount(self, location_id: str, *, user: bool) -> LocationInfo:
        loc = self._cfg(location_id)
        rt = self._state(location_id)
        if rt.mounted:
            return self._info(loc)
        if user:
            rt.user_unmounted = False
        if loc.kind == "usb":
            if not rt.present:
                raise MountFailed("The drive is not connected")
            if not rt.supported:
                raise MountFailed(rt.reason or "Unsupported filesystem")
            rc, out, err = await self._run(["mount-usb", loc.uuid or ""])
        else:
            rc, out, err = await self._mount_smb(loc, self._secrets.get_smb(loc.id))
        if rc != 0:
            rt.error = (err.strip() or out.strip() or f"mount failed (exit {rc})")[:500]
            self._changed("error", location_id)
            raise MountFailed(rt.error, details={"id": location_id})
        try:
            data = json.loads(out)
            root = Path(data["root"])
            fstype = data.get("fstype")
        except (ValueError, KeyError, TypeError) as exc:
            rt.error = "Unexpected helper output"
            raise MountFailed(rt.error) from exc
        rt.mounted, rt.root, rt.error, rt.backoff = True, root, None, 2.0
        self._points.add(str(self.mount_point(location_id)))
        self._live_at = float("-inf")
        rt.encrypted = data.get("encrypted") if isinstance(data.get("encrypted"), bool) else None
        self._gen[location_id] = self._gen.get(location_id, 0) + 1
        rt.fstype = fstype or rt.fstype
        await self._update_free(rt)
        self._changed("mounted", location_id)
        return self._info(loc)

    async def _mount_smb(self, loc: StorageLocation, password: str | None) -> tuple[int, str, str]:
        """Credentials go to the helper on stdin (cifs credentials format), never to disk."""
        slug = loc.id.removeprefix("smb-")
        fields = {"username": loc.username, "password": password, "domain": loc.domain}
        if any(v and ("\n" in v or "\r" in v) for v in fields.values()):
            return 1, "", "Credentials must not contain line breaks"
        creds = None
        if loc.username or password or loc.domain:
            lines = [f"username={loc.username or 'guest'}"]
            if password:
                lines.append(f"password={password}")
            if loc.domain:
                lines.append(f"domain={loc.domain}")
            creds = "\n".join(lines) + "\n"
        return await self._run(["mount-smb", slug, loc.unc or ""], stdin=creds)

    async def unmount(self, location_id: str, *, lazy: bool = False, user: bool = True) -> None:
        self._check_not_checking(location_id)
        async with self._lock:
            await self._unmount(location_id, lazy=lazy, user=user)

    async def _unmount(self, location_id: str, *, lazy: bool, user: bool) -> None:
        self._cfg(location_id)
        rt = self._state(location_id)
        if user and location_id == self._store.config.storage.target_id and self.busy():
            raise InvalidState("Cannot unmount the target while a capture or job is active")
        if not rt.mounted:
            return
        rc, out, err = await self._run(["unmount", location_id, *(["--lazy"] if lazy else [])])
        if rc == EXIT_BUSY:
            raise LocationBusy("The location is in use", details={"id": location_id})
        if rc != 0:
            raise MountFailed((err.strip() or out.strip() or "unmount failed")[:500])
        rt.mounted, rt.root, rt.free, rt.encrypted = False, None, None, None
        self._points.discard(str(self.mount_point(location_id)))
        self._live_at = float("-inf")
        if user:
            rt.user_unmounted = True
        self._changed("unmounted", location_id)

    def check_fsck_allowed(self, location_id: str) -> StorageLocation:
        loc = self._cfg(location_id)
        if loc.kind != "usb":
            raise InvalidState("Only USB drives can be checked")
        self._check_not_checking(location_id)
        if self._state(location_id).mounted:
            raise InvalidState("Unmount the drive before checking it")
        return loc

    async def fsck(self, location_id: str) -> tuple[int, str]:
        # Check-mounted-and-mark-busy is atomic against mount() via the lock, which is
        # released before the long repair so polling and other locations are not stalled.
        async with self._lock:
            loc = self.check_fsck_allowed(location_id)
            self._fsck_busy.add(location_id)
        try:
            rc, out, err = await self._run(["fsck", loc.uuid or ""], limit_s=FSCK_TIMEOUT_S)
        except TimeoutError as exc:
            raise MountFailed(
                "The drive check did not finish in time and was stopped",
                details={"id": location_id},
            ) from exc
        finally:
            self._fsck_busy.discard(location_id)
        return rc, (out + err).strip()

    def check_format_allowed(
        self, disk: str, majmin: str, size: int, diskseq: str
    ) -> list[dict[str, Any]]:
        """Synchronous validation of a format request; returns the detected partitions."""
        items = self._disk_items(disk)
        if not items:
            raise LocationNotFound("No such USB drive is connected", details={"disk": disk})
        ref = items[0]["disk"]
        if (
            ref.get("majmin") != majmin
            or ref.get("size") != size
            or str(ref.get("diskseq") or "") != diskseq
        ):
            raise InvalidState(
                "The drive changed since it was listed; refresh and try again",
                details={"disk": disk},
            )
        cfg = self._store.config.storage
        for i in items:
            lid = self._item_location_id(i)
            if lid == cfg.target_id:
                raise InvalidState(
                    "This drive holds the capture target; choose another target first",
                    details={"id": lid},
                )
            if lid in cfg.backup_ids:
                raise InvalidState(
                    "This drive is a backup destination; remove it from the backups first",
                    details={"id": lid},
                )
        for i in items:
            lid = self._item_location_id(i)
            rt = self._rt.get(lid)
            if i.get("mounted") or (rt is not None and rt.mounted):
                raise InvalidState(
                    "Unmount every partition of this drive before formatting it",
                    details={"id": lid},
                )
        if disk in self._format_busy:
            raise LocationBusy("The drive is being formatted", details={"disk": disk})
        if any(self._item_location_id(i) in self._fsck_busy for i in items):
            raise LocationBusy("A partition of this drive is being checked", details={"disk": disk})
        return items

    async def format_disk(
        self, disk: str, fstype: str, label: str, majmin: str, size: int, diskseq: str
    ) -> list[str]:
        """Erase the whole physical disk and create one partition with a fresh filesystem.
        Returns the ids of saved locations that lived on it (now removed). Like fsck, the
        check-and-mark is atomic under the lock, released before the long operation."""
        if (why := label_error(fstype, label)) is not None:
            raise ConfigInvalid(why)
        if (why := fat32_error(fstype, size)) is not None:
            raise ConfigInvalid(why)
        async with self._lock:
            items = self.check_format_allowed(disk, majmin, size, diskseq)
            self._format_busy.add(disk)
        stale = [self._item_location_id(i) for i in items]
        ok = False
        try:
            args = [
                "format-usb", disk, majmin, str(size), diskseq, fstype, *([label] if label else [])
            ]  # fmt: skip
            try:
                rc, out, err = await self._run(args, limit_s=FORMAT_TIMEOUT_S)
            except TimeoutError as exc:
                raise MountFailed(
                    "The drive format did not finish in time and was stopped",
                    details={"disk": disk},
                ) from exc
            if rc != 0:
                raise MountFailed(
                    (err.strip() or out.strip() or f"format failed (exit {rc})")[:500],
                    details={"disk": disk},
                )
            ok = True
        finally:
            self._format_busy.discard(disk)
            with contextlib.suppress(Exception):
                await self.refresh()  # the new (or, after a failure, changed) layout
        removed: list[str] = []
        if ok:
            saved = {loc.id: loc for loc in self._store.config.storage.locations}
            elsewhere = {
                str(i.get("uuid"))
                for i in self._detected.items.values()
                if i.get("uuid") and (i.get("disk") or {}).get("name") != disk
            }
            for lid in stale:
                loc = saved.get(lid)
                if loc is None or (loc.kind == "usb" and loc.uuid in elsewhere):
                    continue  # never drop a location whose UUID lives on another drive
                try:
                    await self.remove(lid)
                    removed.append(lid)
                except Exception:
                    log.exception("could not remove %s after formatting %s", lid, disk)
        self._changed("formatted", None)
        return removed

    async def test_smb(
        self, unc: str, username: str | None, password: str | None, domain: str | None
    ) -> tuple[bool, str]:
        """Mount a share under a throwaway id and unmount it again."""
        slug = f"test{_secrets.token_hex(4)}"
        loc = StorageLocation(
            id=f"smb-{slug}", kind="smb", unc=unc, username=username, domain=domain
        )
        async with self._lock:
            rc, out, err = await self._mount_smb(loc, password)  # never stored
            if rc != 0:
                return False, (err.strip() or out.strip() or "mount failed")[:500]
            await self._run(["unmount", loc.id])
            return True, "ok"

    async def _probe(self, key: tuple[str, str], fn: Callable[..., Any], *args: Any) -> Any:
        """Run a blocking filesystem probe in the small dedicated pool (a hung mount can
        only stall these threads, never the default executor). A location's next probe is
        refused while its previous one is still pending."""
        prev = self._probes.get(key)
        if prev is not None and not prev.done():
            raise _ProbePending
        fut = asyncio.get_running_loop().run_in_executor(self._probe_pool, fn, *args)
        self._probes[key] = fut

        def _done(f: asyncio.Future[Any]) -> None:
            if self._probes.get(key) is f:
                del self._probes[key]
            if not f.cancelled():
                f.exception()  # mark retrieved

        fut.add_done_callback(_done)
        return await asyncio.wait_for(asyncio.shield(fut), PROBE_TIMEOUT_S)

    async def _update_free(self, rt: _Runtime) -> None:
        if rt.root is None:
            return
        try:
            du = await self._probe((str(rt.root), "free"), shutil.disk_usage, rt.root)
            rt.free, rt.size = du.free, du.total
        except _ProbePending:
            return  # previous probe still hanging: keep the last value
        except (OSError, TimeoutError):
            rt.free = None

    # ---- polling ------------------------------------------------------------------------
    async def start(self) -> None:
        if self._fixed is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._loop(), name="locations-poll")

    async def aclose(self) -> None:
        with contextlib.suppress(TimeoutError):  # a hung probe must not block shutdown
            await asyncio.wait_for(
                asyncio.to_thread(self._probe_pool.shutdown, True, cancel_futures=True), 2.0
            )
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:
                log.exception("location refresh failed")
            await asyncio.sleep(self._poll)

    def _mounted_points(self) -> set[str]:
        try:
            return parse_mountinfo(self._mountinfo.read_text())
        except OSError:
            return set()

    async def refresh(self) -> None:
        """One poll cycle: detect USB drives, reconcile mounts, auto-mount, probe SMB."""
        async with self._lock:
            await self._refresh()

    async def _refresh(self) -> None:
        items: Any = None
        try:
            rc, out, _err = await self._run(["list-usb"])
            items = json.loads(out) if rc == 0 else None
        except (TimeoutError, OSError, ValueError):
            items = None
        usb_ok = isinstance(items, list)
        if usb_ok:
            found = {str(i.get("uuid") or i.get("name")): i for i in items if isinstance(i, dict)}
            if self._format_busy:  # the layout of a disk being formatted is in flux: keep it frozen
                found = {
                    k: i
                    for k, i in found.items()
                    if (i.get("disk") or {}).get("name") not in self._format_busy
                }
                found.update(
                    {
                        k: i
                        for k, i in self._detected.items.items()
                        if (i.get("disk") or {}).get("name") in self._format_busy
                    }
                )
            self._detected = _Detected(found, True)
        points = self._points = await asyncio.to_thread(self._mounted_points)
        self._live_at = time.monotonic()
        for loc in list(self._store.config.storage.locations):
            await self._reconcile(loc, points, usb_ok)

    async def _reconcile(self, loc: StorageLocation, points: set[str], usb_ok: bool) -> None:
        rt = self._state(loc.id)
        item = self._detected.items.get(loc.uuid or "") if loc.kind == "usb" else None
        if loc.kind == "usb" and usb_ok:
            was_present = rt.present
            rt.present = item is not None
            if item is not None:
                rt.fstype = item.get("fstype") or rt.fstype
                rt.label = item.get("label")
                rt.size = item.get("size") or rt.size
                rt.supported = bool(item.get("supported"))
                rt.reason = item.get("reason")
            if not rt.present:
                rt.user_unmounted = False
            if was_present != rt.present and not rt.present and not rt.mounted:
                self._changed("unplugged", loc.id)
        is_mounted = str(self.mount_point(loc.id)) in points
        if rt.mounted and not is_mounted:
            rt.mounted, rt.root = False, None
            self._changed("unmounted", loc.id)
        elif is_mounted and not rt.mounted:
            if item and item.get("root"):
                root = Path(item["root"])  # the helper knows ext4 etc. keep data in <mp>/ncc
            elif item and item.get("mount_path"):
                root = Path(item["mount_path"])
            else:
                root = self.mount_point(loc.id)
            rt.mounted, rt.root = True, root
            self._gen[loc.id] = self._gen.get(loc.id, 0) + 1
            self._changed("mounted", loc.id)
        if loc.kind == "usb" and usb_ok and not rt.present and rt.mounted:
            try:
                await self._unmount(loc.id, lazy=True, user=False)
            except (MountFailed, LocationBusy) as exc:
                log.warning("unmount of unplugged %s failed: %s", loc.id, exc)
                rt.error = str(exc)[:500]
                return  # retried on the next poll; other locations continue
            self._changed("unplugged", loc.id)
            return
        if rt.mounted:
            await self._update_free(rt)
            if loc.kind == "smb" and rt.root is not None and not await self._healthy(rt.root):
                rt.error = "The share became unreachable"
                with contextlib.suppress(Exception):
                    await self._unmount(loc.id, lazy=True, user=False)
                rt.retry_at = time.monotonic() + rt.backoff
                self._changed("unreachable", loc.id)
            return
        want = (
            loc.auto_mount
            and not rt.user_unmounted
            and time.monotonic() >= rt.retry_at
            and loc.id not in self._fsck_busy
            and not (self._format_busy and self._disk_of(loc.id) in self._format_busy)
        )
        if loc.kind == "usb":
            want = want and rt.present and rt.supported
        if want:
            try:
                await self._mount(loc.id, user=False)
            except Exception as exc:
                log.warning("auto-mount of %s failed: %s", loc.id, exc)
                rt.retry_at = time.monotonic() + rt.backoff
                rt.backoff = min(rt.backoff * 2, 60.0)

    async def _healthy(self, root: Path) -> bool:
        try:
            await self._probe((str(root), "health"), os.statvfs, root)
            return True
        except (OSError, TimeoutError, _ProbePending):  # a probe still pending is a hang
            return False
