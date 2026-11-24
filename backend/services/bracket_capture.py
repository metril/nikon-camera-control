"""One-shot bracketed capture: apply each step, shoot, restore the original settings."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.api.schemas.common import EventType
from backend.api.schemas.exposure import BracketRequest, BracketShot
from backend.api.schemas.timelapse import BracketStep, TimelapseSetup
from backend.core.camera_service import CameraService
from backend.core.config_store import ConfigStore
from backend.core.errors import CameraBusy, CameraNotConnected, ConfigInvalid
from backend.core.events import EventBus
from backend.core.jobs import HeldContext, Job, JobContext, JobManager
from backend.services.capture import CaptureService, sanitize_prefix
from backend.services.settings import SettingsService
from backend.services.timelapse.brackets import SETTLE_S, touched_settings
from backend.services.timelapse.config import resolve_config

log = logging.getLogger(__name__)

OWNER = "bracket"


class BracketCaptureService:
    def __init__(
        self,
        camera: CameraService,
        jobs: JobManager,
        bus: EventBus,
        settings: SettingsService,
        capture: CaptureService,
        config: ConfigStore,
        *,
        settle_s: float = SETTLE_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._camera = camera
        self._jobs = jobs
        self._bus = bus
        self._settings = settings
        self._capture = capture
        self._config = config
        self._settle = settle_s
        self._sleep = sleep

    async def resolve(self, req: BracketRequest) -> list[BracketStep]:
        """Steps validated and canonicalised against the connected camera (2-15 required)."""
        # Reuse the time-lapse resolver; interval/frames are placeholders that always pass.
        setup = TimelapseSetup(
            name="bracket", interval_s=86_400, total_frames=1, bracketing=req.bracketing
        )
        resolved = await resolve_config(
            setup, self._config.config.timelapse, settings=self._settings
        )
        if len(resolved.steps) < 2:
            raise ConfigInvalid("A one-shot bracket needs at least 2 steps")
        return resolved.steps

    async def start(self, req: BracketRequest) -> Job:
        st = self._camera.status()
        if not st.connected:
            raise CameraNotConnected()
        if st.leased_by is not None:
            raise CameraBusy(details={"leased_by": st.leased_by})
        steps = await self.resolve(req)
        held = HeldContext(self._camera.lease(OWNER))
        await held.enter()  # 409 now, not inside the job
        try:
            return self._jobs.submit(
                "bracket",
                lambda ctx: self._job(ctx, req, steps, held),
                exclusive_key="bracket",
                release=held.release,
            )
        except BaseException:
            await held.release()
            raise

    async def _job(
        self, ctx: JobContext, req: BracketRequest, steps: list[BracketStep], held: HeldContext
    ) -> dict[str, Any]:
        out_root = self._capture.output_dir
        dest = out_root / "brackets" / datetime.now().strftime("%Y-%m-%d-%H%M%S-%f")
        prefix = sanitize_prefix(req.filename_prefix)
        shots: list[BracketShot] = []
        try:
            snapshot = await self._settings.snapshot(touched_settings(steps))
            try:
                for i, step in enumerate(steps):
                    ctx.report(
                        i / len(steps), f"Step {i + 1}/{len(steps)}: {step.label}".rstrip(": ")
                    )
                    if step.delay_ms:
                        await self._sleep(step.delay_ms / 1000)
                    await self._settings.set_many(dict(step.settings), owner=OWNER)
                    if self._settle:
                        await self._sleep(self._settle)
                    shot = BracketShot(
                        index=i, label=step.label, settings=dict(step.settings), files=[]
                    )
                    if req.download:
                        local = await self._capture.capture_to(
                            dest, owner=OWNER, name_prefix=f"{prefix}{i + 1:02d}-"
                        )
                        shot.files = [_rel(p, out_root) for p in local]
                    else:
                        files = await self._camera.capture(owner=OWNER)
                        shot.camera_files = [f"{f.folder}/{f.name}" for f in files]
                    shots.append(shot)
            finally:
                await self._restore(snapshot)
        finally:
            await held.release()
        return {
            "directory": _rel(dest, out_root) if req.download else None,
            "shots": [s.model_dump() for s in shots],
        }

    async def _restore(self, snapshot: dict[str, Any]) -> None:
        try:
            await asyncio.shield(self._settings.restore(snapshot, owner=OWNER))
        except Exception as e:
            log.exception("could not restore bracket settings")
            self._bus.publish(
                EventType.ERROR,
                {
                    "code": "BRACKET_RESTORE_FAILED",
                    "message": f"Settings may be left changed; originals: {snapshot}",
                    "cause": str(e),
                },
            )


def _rel(p: Path, root: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()
