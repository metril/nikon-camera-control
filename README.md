# Nikon Camera Control

A web app that controls a Nikon D500 over USB: live view, exposure and focus settings, capture with transfer to the host, bulb, bracketing, time-lapse with video rendering, focus stacking, in-camera video recording, a file browser for the camera card and the local gallery. FastAPI backend (`/api/v1`), Vue 3 frontend, shipped as one Docker image.

**Status: developed and tested against a simulated camera only. Nothing has been run on a real D500 yet.** See [docs/HARDWARE_CHECKLIST.md](docs/HARDWARE_CHECKLIST.md).

## Features

- Settings: ISO, aperture, shutter speed, exposure compensation, exposure mode, white balance, image quality/size, metering, focus mode, capture target, camera clock; presets (built-in and your own)
- Live view stream (typically 5-10 fps over USB 2.0), capture during live view
- Capture to the host, one-shot exposure bracket, bulb exposures, trigger-only
- Time-lapse with optional per-frame bracket sets, sessions, and video rendering (ffmpeg)
- Focus: autofocus drive, manual focus drive, focus stacking
- In-camera video recording
- Camera card browser: download selected or all new files, delete
- Gallery with cached thumbnails (NEF embedded previews)
- Live events over WebSocket; jobs with progress and cancel

## Camera setup (important)

- **The mode dial must be on P, A, S or M.** In Auto, scene or effects modes settings changes silently fail.
- Use a good USB cable directly into a host port (no unpowered hubs). Power the camera on before starting.
- The D500 powers down its link after 60 s of inactivity; the app sends keepalives (configurable).

## Quick start (Docker)

```bash
sudo cp docker/udev/99-nikon.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger   # then replug the camera
cd docker
mkdir -p data && sudo chown 1000:1000 data
docker compose -f compose.yaml up -d   # pulls ghcr.io/metril/nikon-camera-control (amd64 and arm64)
```

**Version:** `docker/compose.yaml` pins a release tag (`image: ghcr.io/metril/nikon-camera-control:0.5.5`). Edit the tag to pick another version (`0.2` follows the latest patch of a minor, `latest` the newest release). **Upgrade:** change the tag, then `docker compose -f compose.yaml pull && docker compose -f compose.yaml up -d`. Your `data/` is kept.

Open http://localhost:8000 and press Connect. Replugging or power-cycling the camera does not require a container restart (the compose file bind-mounts `/dev/bus/usb`, so the new device node is visible).

`docker/data` (config only) is bind-mounted (paths relative to the compose file). The container runs as uid/gid 1000 and gets USB access through `group_add`, which must be the **numeric gid that owns the camera node on the host** (default `"46"`, Debian/Ubuntu `plugdev`). With the camera plugged in, check `stat -c %g /dev/bus/usb/BBB/DDD` (BBB/DDD from `lsusb`); if it is not 46 (or `plugdev` does not exist, e.g. Fedora/Arch), edit `group_add` in `docker/compose.yaml`. The udev rule is what sets that group on the node. No privileged mode and no environment variables; storage mounting needs the extra privileges described under Storage below.

## First-run setup in the web UI

Everything is configured on the **Settings** page (stored in `data/config.json`):

- Camera: keepalive on/off and interval, connect timeout, reconnect attempts and interval, capture timeout, event quiet window
- Live view: target fps, frame size, JPEG quality, max width
- Time-lapse: minimum interval, maximum duration, failure budget
- Video: ffmpeg path, codec, CRF, preset, fps, timeout
- Thumbnails: size
- CORS origins (restart required)
- **Demo camera**: a simulated D500, so you can try every feature without hardware
- **API key**: generate or remove

### API key

The app is open until you generate a key in Settings (shown once; only its sha256 is stored in `data/api_key.json`). Clients then send it as the `X-API-Key` header; WebSocket clients, which cannot set headers, offer the subprotocol `apikey.<key>`. **Lockout recovery:** delete `data/api_key.json` on the host and restart the container (`docker compose restart`); the app is open again. A corrupt key file locks everyone out (fail closed) until deleted.

## API

The REST and WebSocket API lives under `/api/v1`. The OpenAPI spec (`openapi.json`), the reference ([docs/API.md](docs/API.md)) and the frontend client are all generated from the code by `make api` and checked for drift by `make api-check` (also part of CI); a running instance serves interactive docs at `/docs`. Nothing about endpoints is hand-written here.

```bash
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/camera/connect -H "X-API-Key: $KEY"
curl -X POST http://localhost:8000/api/v1/capture -H "X-API-Key: $KEY"
```

## Development

Requires Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) (or plain venv) and [bun](https://bun.sh).

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
(cd frontend && bun install --frozen-lockfile)

make lint test      # ruff, mypy, pytest (parallel)
make api            # regenerate openapi.json, docs/API.md and the frontend client
make ci             # everything CI runs, except the Docker build (make docker-build)
make docker-build   # build the image locally from the Dockerfile
```

Run with the demo camera: put `{"demo_camera": true}` in `data/config.json`, then

```bash
.venv/bin/uvicorn backend.asgi:create --factory --port 8000   # terminal 1
cd frontend && bun run dev                                    # terminal 2 -> http://localhost:5173
```

The Vite proxy (`/api`, including WebSockets) keeps the browser's `Host` (`changeOrigin: false`) so it matches the `Origin` header; the backend rejects cross-origin unsafe requests (see Security notes), so do not turn `changeOrigin` on. If you open the dev server from another host name, add that origin to `cors_origins`.

Hardware tests (skipped by default; one camera, so no xdist): `.venv/bin/pytest -m hardware --real-camera -n 0 -s tests/hardware`. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Storage

Captures go to a storage location chosen in the web UI: a USB drive (mounted inside the container) or an SMB share. USB filesystems: exFAT, FAT, NTFS (ntfs3), ext2/3/4, btrfs, XFS, F2FS, HFS+ (non-journaled only). Encrypted (LUKS), APFS and swap volumes are listed but cannot be used. A "Check & repair" action runs the filesystem's fsck while unmounted. Prefer exFAT or a POSIX filesystem: FAT32 caps files at 4 GiB.

## Data layout

- `data/` (config): `config.json`, `api_key.json`, `presets.json`, `downloaded.jsonl` (ledger of cards files already pulled), thumbnail cache, temp dirs
- Captures (`sessions/`, `camera/`, `recordings/`, stills) are written to the selected USB or SMB storage location, never to the host. Nothing is stored on the host except `data/`.

## Security notes

- No authentication until a key is generated. Meant for a trusted LAN; do not expose it to the internet. Put it behind a reverse proxy with TLS if you need remote access.
- The app runs non-root and is not `--privileged`. For storage mounting it adds `SYS_ADMIN`, `MKNOD`, `apparmor:unconfined` and block-device cgroup rules (8, 259, 179); sudo allows the app to run only `/usr/local/sbin/ncc-storage`, which validates every argument and only touches USB-backed devices (see comments in `docker/compose.yaml`).
- `docker/udev/99-nikon.rules` grants the `plugdev` group (mode 0660), not everyone; `group_add` in the compose file must be that group's numeric gid on the host.
- Cross-origin protection: POST/PUT/PATCH/DELETE requests and WebSocket handshakes that carry an `Origin` header must be same-origin (same host:port as `Host`, scheme ignored) or listed in `cors_origins` (read live), otherwise they get 403 `FORBIDDEN_ORIGIN` (WebSocket: close code 4403). This stops other web pages on the LAN from driving the camera in open mode. Requests without `Origin` (curl, scripts) are unaffected, so it is not a substitute for an API key. Behind a reverse proxy that rewrites `Host`, add the public origin to `cors_origins`.
- Rotating, removing or creating the API key closes open WebSockets with code 4401.

## Touchscreen kiosk

An optional `kiosk` service shows the touch UI full-screen on the host's HDMI output (cage + Chromium in a container; the host needs no desktop, display server or browser).

```bash
stat -c %g /dev/dri/card0 /dev/dri/renderD128 /dev/input/event0   # put these gids in group_add
docker compose -f docker/compose.yaml --profile kiosk up -d
```

- `group_add` in the `kiosk` service takes the host's numeric gids for video, render and input (defaults 44, 992, 996 on Debian 13).
- The container starts as root only to run `seatd`, then cage and Chromium run as an unprivileged user. Not privileged, no added capabilities; Chromium runs with `--no-sandbox` because the container is the sandbox.
- `/dev/input` is bind-mounted with a device cgroup rule, and the entrypoint watches `/run/udev/data` (inotify), so a touchscreen that is unplugged and replugged works again within seconds (the compositor restarts). udev events don't reach the container, so libinput can't see hotplug itself.
- Display scale: Settings > Display > "Kiosk display scale" (Auto, 1x, 1.25x, 1.5x, 2x). Auto derives it from the screen's EDID physical size and resolution (about 96 PPI = 1x, clamped to 1-2x, 1x if unknown). A change relaunches the kiosk browser. The kiosk reads it from the open `GET /api/v1/kiosk/scale` event stream.
- Rotate the screen: run `docker exec nikon-camera-control-kiosk wlr-randr --output HDMI-A-1 --transform 90` (env `WAYLAND_DISPLAY`/`XDG_RUNTIME_DIR=/tmp/xdg` may be needed, run as user `kiosk`), or add cage's `-r` flag in `docker/kiosk/entrypoint.sh`.
- Check GPU acceleration: open `chrome://gpu` on the kiosk (or `docker logs nikon-camera-control-kiosk`) and look for hardware acceleration and VA-API.

## Releases

1. Bump `__version__` in `backend/__init__.py`, `version` in `frontend/package.json` and the image tag in `docker/compose.yaml` (check with `make release-check`).
2. Commit, then `git tag vX.Y.Z && git push --tags`.
3. CI (`.github/workflows/release.yml`) verifies the versions match the tag, publishes the multi-arch app and kiosk images to GHCR and creates the GitHub release.

## Known limitations

| Limitation | Description |
|---|---|
| Mode dial | Must be P/A/S/M or settings fail silently |
| Live view fps | USB 2.0 bandwidth limits to roughly 5-10 fps |
| Focus points | Cannot be selected remotely; only AF mode and focus drive |
| RAW+JPEG | Expected to return both files; unverified on hardware |
| Time-lapse jitter | Software intervalometer, about +/-500 ms per frame |
| Extended ISO / Kelvin | Extended ISO and numeric Kelvin may not be settable remotely |
| Video recording | Uses the `movie` widget; behaviour on the D500 is unverified, clips are limited to 29:59 |

## Troubleshooting

- **Camera not detected:** check the cable and power, the mode dial, `lsusb | grep Nikon`, that the udev rule is installed (`ls /etc/udev/rules.d/99-nikon.rules`) and the camera was replugged afterwards.
- **"Device claimed by another process":** a desktop auto-mounter (gvfs) or `gphoto2` has the camera; `pkill -f gvfs-gphoto2-volume-monitor` and retry.
- **Settings not applying:** mode dial (above). Aperture needs A or M, shutter speed S or M; Auto-ISO can override manual ISO.
- **Live view freezes:** the 60 s link timeout may have hit; keep keepalive enabled; disconnect and reconnect.
- **Container cannot reach USB:** `ls -la /dev/bus/usb/*/` should show mode 0660 and the group whose numeric gid (`stat -c %g`) equals `group_add` in the compose file (default 46). `docker compose logs -f` shows connect errors.
- **Cannot write data:** `sudo chown -R 1000:1000 data`.
- **Locked out:** delete `data/api_key.json`.
