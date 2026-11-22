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
mkdir -p data output && sudo chown 1000:1000 data output
docker compose up -d --build
```

Open http://localhost:8000 and press Connect. Replugging the camera does not require a container restart.

`docker/data` and `docker/output` are bind-mounted (paths relative to the compose file). The container runs as uid/gid 1000 in the `plugdev` group; no privileged mode, no extra capabilities, no environment variables.

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
```

Run with the demo camera: put `{"demo_camera": true}` in `data/config.json`, then

```bash
.venv/bin/uvicorn backend.asgi:create --factory --port 8000   # terminal 1
cd frontend && bun run dev                                    # terminal 2 -> http://localhost:5173
```

Hardware tests (skipped by default; one camera, so no xdist): `.venv/bin/pytest -m hardware --real-camera -n 0 -s tests/hardware`. Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Data layout

- `data/` (config): `config.json`, `api_key.json`, `presets.json`, `downloaded.jsonl` (ledger of cards files already pulled), thumbnail cache, temp dirs
- `output/`: `sessions/` (time-lapse sessions and rendered videos), `camera/` (downloads from the card), `recordings/` (video clips), captured stills

## Security notes

- No authentication until a key is generated. Meant for a trusted LAN; do not expose it to the internet. Put it behind a reverse proxy with TLS if you need remote access.
- The container is non-root, not privileged, and gets only `/dev/bus/usb` (see the trade-off comment in `docker/docker-compose.yml`).
- `docker/udev/99-nikon.rules` grants the `plugdev` group (mode 0660), not everyone.

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
- **Container cannot reach USB:** `ls -la /dev/bus/usb/*/` should show group `plugdev` and mode 0660 on the camera node. `docker compose logs -f` shows connect errors. If the host's plugdev gid is not 46, put its numeric gid under `group_add`.
- **Cannot write data/output:** `sudo chown -R 1000:1000 data output`.
- **Locked out:** delete `data/api_key.json`.
