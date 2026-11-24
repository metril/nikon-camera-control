"""Capture downloads: RAM/card targets, late RAW+JPEG files, keep-card-copy, host location loss."""

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from backend.camera.fake import CARD_FOLDER, FakeCamera
from backend.core.errors import CameraOperationFailed, DownloadFailed, NoTargetError
from backend.core.storage_root import FixedRoot
from backend.services.capture import CaptureService

MSG = "The photo was taken, but it couldn't be copied from the camera."


@pytest.fixture
def fake_camera() -> FakeCamera:
    return FakeCamera(late_second_file=True)


class Gone:
    """A host location that is not mounted."""

    def root(self) -> Path:
        raise NoTargetError("The storage target is not mounted.")

    def stored(self, path: Path) -> None: ...


def _svc(app: FastAPI, store: object, keep: bool = True) -> CaptureService:
    index = SimpleNamespace(invalidate=lambda: None)
    return CaptureService(
        app.state.camera_service,
        store,
        index,
        keep_card_copy=lambda: keep,  # type: ignore[arg-type]
    )


async def _setup(app: FastAPI, target: str, quality: str) -> None:
    await app.state.camera_service.connect()
    cs = app.state.camera_service
    await cs.call(lambda b: b.set_config("capturetarget", target))
    await cs.set_setting("imagequality", quality)


async def _shot(svc: CaptureService):
    return await svc.capture(download=True, delete_from_camera=False, filename_prefix=None)


async def test_ram_raw_jpeg_late_second_file_downloads_both(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Internal RAM", "NEF+JPEG Fine")
        res = await _shot(_svc(app, FixedRoot(tmp_dirs.output_dir)))
    assert [f.name for f in res.camera_files] == ["capt0000.jpg", "capt0001.nef"]
    assert {p.suffix for p in res.local} == {".jpg", ".nef"}
    assert all(p.stat().st_size > 0 and p.parent == tmp_dirs.output_dir for p in res.local)


@pytest.mark.parametrize(
    ("quality", "suffixes"), [("JPEG Fine", {".JPG"}), ("NEF (Raw)", {".NEF"})]
)
async def test_single_file_shots(app: FastAPI, tmp_dirs, quality: str, suffixes: set[str]) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", quality)
        res = await _shot(_svc(app, FixedRoot(tmp_dirs.output_dir)))
    assert {p.suffix for p in res.local} == suffixes and len(res.camera_files) == 1


async def test_keep_card_copy_false_deletes_only_after_verified_download(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "NEF+JPEG Fine")
        res = await _svc(app, FixedRoot(tmp_dirs.output_dir), keep=False).capture(
            download=True, delete_from_camera=False, filename_prefix=None
        )
        assert len(res.local) == 2 and fake_camera._files[CARD_FOLDER] == {}
        # a size the camera disagrees with is not verified: the card copy stays
        real = fake_camera.file_info
        fake_camera.file_info = lambda folder, name: dataclasses.replace(  # type: ignore[method-assign]
            real(folder, name), size=real(folder, name).size + 1
        )
        await _svc(app, FixedRoot(tmp_dirs.output_dir), keep=False).capture(
            download=True, delete_from_camera=False, filename_prefix=None
        )
        assert len(fake_camera._files[CARD_FOLDER]) == 2


async def test_keep_card_copy_default_keeps_files(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "JPEG Fine")
        await _shot(_svc(app, FixedRoot(tmp_dirs.output_dir)))
    assert len(fake_camera._files[CARD_FOLDER]) == 1


async def test_ram_target_never_deletes(app: FastAPI, tmp_dirs, fake_camera: FakeCamera) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Internal RAM", "JPEG Fine")
        res = await _svc(app, FixedRoot(tmp_dirs.output_dir), keep=False).capture(
            download=True, delete_from_camera=True, filename_prefix=None
        )
    assert len(res.local) == 1 and fake_camera.calls.get("delete_file", 0) == 0


async def test_host_unavailable_ram_refuses_before_shooting(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Internal RAM", "JPEG Fine")
        with pytest.raises(NoTargetError) as ei:
            await _shot(_svc(app, Gone()))
    assert fake_camera.calls.get("capture", 0) == 0
    assert "photo was not taken" in ei.value.message


async def test_host_unavailable_card_keeps_photo_on_card(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "JPEG Fine")
        with pytest.raises(NoTargetError) as ei:
            await _shot(_svc(app, Gone(), keep=False))
    assert len(fake_camera._files[CARD_FOLDER]) == 1  # never deleted
    assert "still on the camera card" in ei.value.message
    assert ei.value.details["camera_files"][0]["folder"] == CARD_FOLDER


async def test_download_failure_message_is_user_facing(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "JPEG Fine")
        fake_camera.fail_next("read_file", exc=CameraOperationFailed("read_file(//x): Unspecified"))
        with pytest.raises(DownloadFailed) as ei:
            await _shot(_svc(app, FixedRoot(tmp_dirs.output_dir)))
    e = ei.value
    assert e.message == MSG and "_" not in e.message and "//" not in e.message
    assert (
        "Unspecified" in e.details["cause"] and e.details["cause_code"] == "CAMERA_OPERATION_FAILED"
    )
    assert e.details["camera_files"] and e.http_status == 502


async def test_download_failure_lists_only_unsaved_files(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "NEF+JPEG Fine")
        real = fake_camera.read_file
        calls = []

        def flaky(folder, name, kind, dest):
            calls.append(name)
            if len(calls) == 2:
                raise CameraOperationFailed("boom")
            real(folder, name, kind, dest)

        fake_camera.read_file = flaky  # type: ignore[method-assign]
        with pytest.raises(DownloadFailed) as ei:
            await _svc(app, FixedRoot(tmp_dirs.output_dir), keep=False).capture(
                download=True, delete_from_camera=False, filename_prefix=None
            )
    assert [f["name"] for f in ei.value.details["camera_files"]] == [calls[1]]


async def test_unknown_target_and_host_unavailable_refuses_before_shooting(
    app: FastAPI, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "JPEG Fine")
        fake_camera.fail_next("get_config", exc=CameraOperationFailed("x"))
        with pytest.raises(NoTargetError):
            await _shot(_svc(app, Gone()))
    assert fake_camera.calls.get("capture", 0) == 0


async def test_unknown_target_never_deletes(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    async with app.router.lifespan_context(app):
        await _setup(app, "Memory card", "JPEG Fine")
        fake_camera.fail_next("get_config", exc=CameraOperationFailed("x"))
        await _svc(app, FixedRoot(tmp_dirs.output_dir), keep=False).capture(
            download=True, delete_from_camera=True, filename_prefix=None
        )
    assert len(fake_camera._files[CARD_FOLDER]) == 1


async def test_ram_numbering_restart_after_reconnect_keeps_both_files(
    app: FastAPI, tmp_dirs, fake_camera: FakeCamera
) -> None:
    import asyncio

    fake_camera.ram_numbering_resets = True
    async with app.router.lifespan_context(app):
        await _setup(app, "Internal RAM", "NEF+JPEG Fine")
        cs = app.state.camera_service
        svc = _svc(app, FixedRoot(tmp_dirs.output_dir))
        for _ in range(2):
            res = await _shot(svc)
            assert len(res.local) == 2
        fake_camera.unplug()
        with pytest.raises(Exception, match="unplugged"):
            await cs.call(lambda b: b.summary(), retry=False)
        fake_camera.replug()
        for _ in range(100):
            if cs.status().connected:
                break
            await asyncio.sleep(0.1)
        for _ in range(2):
            res = await _shot(svc)
            assert [f.name for f in res.camera_files] == ["capt0000.jpg", "capt0001.nef"] or len(
                res.local
            ) == 2
            assert {p.suffix for p in res.local} == {".jpg", ".nef"}
        await asyncio.sleep(0.3)
    names = sorted(p.name for p in tmp_dirs.output_dir.iterdir())
    assert len(names) == 8, names
