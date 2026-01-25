"""
Photo Capture API Routes

Endpoints for capturing photos and managing files.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.camera.capture import CaptureHandler
from backend.camera.exceptions import (
    CameraDisconnectedError,
    CaptureError,
    FileTransferError,
)
from backend.config import settings
from backend.models.camera import (
    CapturedFile,
    CaptureRequest,
    CaptureResponse,
    FileListResponse,
)

router = APIRouter(prefix="/api/capture", tags=["capture"])


def get_capture_handler():
    """Get capture handler from controller."""
    from backend.main import camera_controller

    if not camera_controller.is_connected:
        raise HTTPException(status_code=503, detail="Camera not connected")

    return CaptureHandler(
        camera_controller._camera,
        camera_controller._context,
        camera_controller._lock,
        camera_controller
    )


@router.post("/photo", response_model=CaptureResponse)
async def capture_photo(request: CaptureRequest = CaptureRequest()):
    """
    Capture a photo.

    The camera will take a photo and optionally download it to local storage.

    Note: If live view is active, it will be paused during capture.

    Args:
        request: Capture options (download, delete_from_camera)

    Returns:
        Capture result with file path and size.

    Raises:
        503: Camera not connected or capture failed.
    """
    handler = get_capture_handler()

    try:
        result = await handler.capture_photo(
            download=request.download,
            delete_from_camera=request.delete_from_camera
        )

        return CaptureResponse(
            success=True,
            filename=result.get("filename"),
            path=result.get("local_path"),
            size=result.get("size"),
            message="Photo captured successfully"
        )

    except CaptureError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except FileTransferError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/trigger")
async def trigger_capture():
    """
    Trigger capture without waiting for result.

    Useful for burst mode or when file transfer is handled separately.
    """
    handler = get_capture_handler()

    try:
        await handler.trigger_capture()
        return {
            "success": True,
            "message": "Capture triggered",
            "timestamp": datetime.now().isoformat()
        }
    except CaptureError as e:
        raise HTTPException(status_code=503, detail=str(e))


# =============================================================================
# File Management Routes
# =============================================================================

@router.get("/files", response_model=FileListResponse)
async def list_captured_files(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """
    List captured files in the output directory.

    Returns files sorted by modification time (newest first).
    """
    output_path = settings.media.output_path

    if not output_path.exists():
        return FileListResponse(files=[], total=0, page=page, per_page=per_page)

    # Get all image/video files
    extensions = {'.nef', '.jpg', '.jpeg', '.raw', '.tif', '.tiff', '.mp4', '.mov'}
    all_files = [
        f for f in output_path.iterdir()
        if f.is_file() and f.suffix.lower() in extensions
    ]

    # Sort by modification time (newest first)
    all_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    page_files = all_files[start:end]

    # Convert to response format
    files = [
        CapturedFile(
            filename=f.name,
            path=str(f),
            size=f.stat().st_size,
            created=datetime.fromtimestamp(f.stat().st_mtime),
            thumbnail_url=f"/api/capture/thumbnail/{f.name}" if f.suffix.lower() in {'.jpg', '.jpeg'} else None
        )
        for f in page_files
    ]

    return FileListResponse(
        files=files,
        total=len(all_files),
        page=page,
        per_page=per_page
    )


@router.get("/files/{filename}")
async def get_file(filename: str):
    """
    Download a captured file.

    Args:
        filename: Name of the file to download.

    Returns:
        File contents.
    """
    file_path = settings.media.output_path / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/thumbnail/{filename}")
async def get_thumbnail(filename: str):
    """
    Get a thumbnail of a captured image.

    Args:
        filename: Name of the image file.

    Returns:
        Thumbnail image (JPEG).
    """
    file_path = settings.media.output_path / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # For now, return the original file for JPEG
    # In production, generate actual thumbnails
    if file_path.suffix.lower() in {'.jpg', '.jpeg'}:
        return FileResponse(
            path=file_path,
            media_type="image/jpeg"
        )

    raise HTTPException(
        status_code=501,
        detail="Thumbnail generation not implemented for this file type"
    )


@router.delete("/files/{filename}")
async def delete_file(filename: str):
    """
    Delete a captured file.

    Args:
        filename: Name of the file to delete.
    """
    file_path = settings.media.output_path / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_path.unlink()

    return {
        "success": True,
        "message": f"Deleted {filename}",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/camera-files")
async def list_camera_files():
    """
    List files currently on the camera.

    Returns files on the camera's memory card.
    """
    handler = get_capture_handler()

    try:
        files = await handler.list_camera_files()
        return {
            "files": files,
            "total": len(files)
        }
    except CameraDisconnectedError:
        raise HTTPException(status_code=503, detail="Camera not connected")


@router.post("/download-all")
async def download_all_from_camera(delete_after: bool = False):
    """
    Download all files from the camera.

    Args:
        delete_after: If True, delete files from camera after download.

    Returns:
        List of downloaded file paths.
    """
    handler = get_capture_handler()

    try:
        downloaded = await handler.download_all_new_files(delete_after=delete_after)
        return {
            "success": True,
            "files_downloaded": len(downloaded),
            "paths": [str(p) for p in downloaded],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
