"""Storage location, target, backup, offload and verify API models. Passwords are write-only."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

_NO_CTRL = r"^[^\x00-\x1f,]*$"
UNC_PATTERN = r"^//[A-Za-z0-9._-]+/[A-Za-z0-9._ $-]+(/[A-Za-z0-9._ $-]+)*$"


class LocationOut(BaseModel):
    id: str = Field(description="usb-<uuid> or smb-<slug>; dev-<name> for drives without uuid")
    kind: Literal["usb", "smb"]
    name: str
    uuid: str | None = None
    unc: str | None = None
    username: str | None = None
    domain: str | None = None
    auto_mount: bool
    configured: bool = Field(description="False for a detected drive that is not registered yet")
    present: bool = Field(description="USB: connected. SMB: no known failure.")
    mounted: bool
    supported: bool
    reason: str | None = Field(default=None, description="Why the drive cannot be mounted")
    fstype: str | None = None
    label: str | None = None
    size: int | None = Field(default=None, description="Total bytes")
    free: int | None = Field(default=None, description="Free bytes (mounted only)")
    error: str | None = Field(default=None, description="Last mount/health error, verbatim")
    has_password: bool = Field(description="A password is stored (never returned)")
    is_target: bool
    is_backup: bool
    encrypted: bool | None = Field(
        default=None, description="SMB: the session is encrypted (SMB3 seal); false = plaintext"
    )


class LocationsOut(BaseModel):
    locations: list[LocationOut]
    target_id: str | None = None
    backup_ids: list[str] = Field(default_factory=list)


class LocationCreate(BaseModel):
    kind: Literal["usb", "smb"]
    name: str = Field(default="", max_length=64)
    uuid: str | None = Field(default=None, pattern=r"^[0-9A-Za-z-]{1,64}$", description="usb")
    unc: str | None = Field(
        default=None, pattern=UNC_PATTERN, description="smb: //host/share[/sub]"
    )
    username: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)
    password: str | None = Field(
        default=None, max_length=256, pattern=r"^[^\x00-\x1f]*$", description="Write-only"
    )
    domain: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)
    auto_mount: bool = True


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    unc: str | None = Field(default=None, pattern=UNC_PATTERN)
    username: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)
    password: str | None = Field(
        default=None,
        max_length=256,
        pattern=r"^[^\x00-\x1f]*$",
        description="Write-only; empty string removes the stored password",
    )
    domain: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)
    auto_mount: bool | None = None


class SmbTest(BaseModel):
    unc: str = Field(pattern=UNC_PATTERN)
    username: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)
    password: str | None = Field(default=None, max_length=256, pattern=r"^[^\x00-\x1f]*$")
    domain: str | None = Field(default=None, max_length=128, pattern=_NO_CTRL)


class SmbTestResult(BaseModel):
    ok: bool
    message: str


class FsckResult(BaseModel):
    returncode: int
    output: str


class TargetSet(BaseModel):
    id: str | None = Field(description="Location id, or null for no target")


class BackupsSet(BaseModel):
    ids: list[str]


class BackupStatusOut(BaseModel):
    running: bool
    pending: int
    copied: int
    failed: int
    current: str | None = None
    last_run: datetime | None = None
    last_error: str | None = None
    source_id: str | None = None
    backups_online: list[str] = Field(default_factory=list)
    backup_ids: list[str] = Field(default_factory=list)


class OffloadScope(BaseModel):
    kind: Literal["all", "session", "older_than"]
    session_id: str | None = Field(default=None, description="For kind=session")
    before: datetime | None = Field(default=None, description="For kind=older_than")


class OffloadRequest(BaseModel):
    from_id: str
    to_id: str
    scope: OffloadScope
    keep_source: bool = Field(default=False, description="Verified copy only; keep the source")


class VerifyRequest(BaseModel):
    location_id: str | None = Field(default=None, description="Default: the target")
    folder: str = Field(default="", description="Sub-folder to check, relative to the root")
