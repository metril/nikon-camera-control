"""Demo-camera server for the browser layout tests (frontend/e2e).

Usage: python -m scripts.e2e_server PORT. Uses a throwaway data dir, the simulated camera and a
few seeded images, and serves frontend/dist.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

import uvicorn
from PIL import Image

from backend.app import create_app
from backend.core.paths import REPO_ROOT


def _seed(output: Path, count: int = 24) -> None:
    folder = output / "2026-01-01"
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        buf = io.BytesIO()
        Image.new("RGB", (320, 240), (i * 10 % 256, 90, 160)).save(buf, "JPEG")
        (folder / f"DSC_{i:04d}.JPG").write_bytes(buf.getvalue())


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    root = Path(tempfile.mkdtemp(prefix="ncc-e2e-"))
    data, output = root / "data", root / "output"
    data.mkdir()
    output.mkdir()
    (data / "config.json").write_text(json.dumps({"demo_camera": True}))
    _seed(output)
    app = create_app(
        data_dir=data,
        target_dir=output,
        frontend_dist=REPO_ROOT / "frontend" / "dist",
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
