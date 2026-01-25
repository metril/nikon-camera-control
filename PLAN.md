# Nikon D500 Camera Control Application - Implementation Plan

## Overview
A web-based application to control a Nikon D500 camera via USB, featuring real-time Live View, full settings control, media capture/transfer, and **time-lapse creation**.

---

## Critical Constraints (From Expert Review)

### Camera Constraints
- **Mode Dial Requirement**: Camera MUST be set to P/A/S/M mode. Other modes cause settings to silently fail.
- **Live View Timeout**: Camera auto-disconnects after 60 seconds without commands. **Keep-alive pings every 30 seconds required.**
- **Realistic Frame Rate**: 5-10 FPS for Live View (NOT 15 FPS). USB 2.0 bandwidth is the bottleneck.
- **Video Recording**: Problematic via PTP - defer to Phase 3+ or remove entirely.

### Architecture Constraints
- **gphoto2 is blocking**: Use `threading.Lock` (not `asyncio.Lock`). Wrap camera calls with `asyncio.to_thread()`.
- **State Machine Required**: Camera can only be in ONE state: IDLE, LIVEVIEW, CAPTURING, or RECORDING.
- **No concurrent PTP operations**: Queue all camera commands sequentially.

### Dependencies to Change
- Replace `ffmpeg-python` (dead project) with `imageio-ffmpeg` or subprocess calls
- Pin all library versions exactly (no `>=` ranges for system-level packages)

---

## Technology Stack
| Component | Technology | Notes |
|-----------|------------|-------|
| Backend | Python 3.11 + FastAPI | Async HTTP, but camera ops run in thread pool |
| Camera Control | python-gphoto2==2.5.0 | Pin exact version; blocking calls |
| Live View | WebSocket (binary frames) | ~5-10 FPS realistic |
| Frontend | Vue 3 + TailwindCSS | Better state management than vanilla JS |
| Video Encoding | FFmpeg (subprocess) | For time-lapse video generation |
| Deployment | Docker (non-privileged) | USB device passthrough, no --privileged |

## Architecture
```
Browser (WebUI)  <--WebSocket/REST-->  FastAPI Backend  <--PTP/USB-->  Nikon D500
                                              |
                                       Host Volume (captured media)
```

## Project Structure
```
nikon-camera-control/
├── docker/
│   ├── Dockerfile                 # Multi-stage build, pinned versions
│   ├── docker-compose.yml         # USB passthrough (non-privileged)
│   └── udev/
│       └── 99-nikon.rules         # USB device permissions
├── backend/
│   ├── main.py                    # FastAPI entry point
│   ├── config.py                  # Pydantic settings configuration
│   ├── camera/
│   │   ├── controller.py          # Camera connection + state machine
│   │   ├── state.py               # CameraState enum (IDLE/LIVEVIEW/CAPTURING)
│   │   ├── keepalive.py           # 30-second ping mechanism
│   │   ├── settings.py            # Settings discovery/control
│   │   ├── live_view.py           # Live View streaming (5-10 FPS)
│   │   ├── capture.py             # Photo capture (video deferred)
│   │   ├── timelapse.py           # Time-lapse scheduling
│   │   └── exceptions.py          # Comprehensive error hierarchy
│   ├── api/
│   │   ├── routes/
│   │   │   ├── camera.py          # Camera REST endpoints
│   │   │   ├── settings.py        # Settings endpoints
│   │   │   ├── capture.py         # Capture endpoints
│   │   │   ├── timelapse.py       # Time-lapse endpoints
│   │   │   └── files.py           # File management + gallery
│   │   └── websocket/
│   │       ├── live_view.py       # Binary WebSocket streaming
│   │       └── events.py          # Camera status events
│   ├── models/                    # Pydantic models
│   └── services/                  # Business logic layer
│       ├── capture_service.py     # Orchestrates capture + transfer
│       └── timelapse_service.py   # Manages scheduling
├── frontend/                      # Vue 3 SPA
│   ├── index.html
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.js
│   │   ├── components/
│   │   │   ├── LiveView.vue       # Canvas + overlays
│   │   │   ├── SettingsPanel.vue  # Sliders/buttons (not dropdowns)
│   │   │   ├── CaptureControls.vue
│   │   │   ├── TimelapsePanel.vue
│   │   │   ├── Histogram.vue      # Real-time histogram
│   │   │   └── Gallery.vue        # File browser
│   │   ├── composables/
│   │   │   ├── useCamera.js       # Camera state
│   │   │   └── useWebSocket.js    # WebSocket connection
│   │   └── stores/
│   │       └── camera.js          # Pinia state store
│   ├── vite.config.js
│   └── package.json
├── tests/
│   ├── test_camera_controller.py
│   ├── test_state_machine.py
│   └── test_api.py
├── requirements.txt
└── README.md
```

## Implementation Phases

### Phase 1: Foundation & Camera Connection
- Create project structure
- Set up Docker with gphoto2 dependencies (pinned versions)
- USB passthrough WITHOUT privileged mode (use device rules)
- Implement `CameraController` class with:
  - **State machine**: IDLE → LIVEVIEW → CAPTURING states
  - **Keep-alive pings** every 30 seconds (critical for D500)
  - **Threading.Lock** for thread-safe camera operations
  - Connection retry with exponential backoff
- Basic FastAPI app with health endpoint
- Verify D500 detection in container
- **Add README warning**: Mode dial MUST be in P/A/S/M

### Phase 2: Camera Settings Control
- Implement `CameraSettingsManager` class
- Settings discovery API (`/api/settings`)
- Get/set endpoints for:
  - ISO (100-51200, document extended modes may fail)
  - Aperture, Shutter Speed (behavior depends on mode dial)
  - Exposure Mode, Focus Mode (AF-S/AF-C/MF only)
  - White Balance (presets only, Kelvin may fail)
  - Image Format (single format recommended, RAW+JPEG is best-effort)
  - Metering Mode
- Handle read-only settings gracefully with clear error messages
- Add battery level reading
- Test each setting on actual D500 before marking complete

### Phase 3: Live View Streaming
- Implement `LiveViewHandler` with frame capture loop
- **Target 5-10 FPS** (not 15 - USB 2.0 is the bottleneck)
- Integrate with keep-alive mechanism
- WebSocket endpoint (`/ws/liveview`) with **binary frames**
- Implement timeout recovery (auto-restart if camera times out)
- Add frame rate indicator for debugging
- **State machine integration**: Auto-stop live view before capture

### Phase 4: Photo Capture
- Implement `CaptureHandler` class
- Photo capture endpoint (`POST /api/capture/photo`)
- Add 2-second delay after capture before polling for files
- Download files to user-specified output folder
- Capture event notifications via WebSocket
- File transfer verification (size check)
- **Video recording DEFERRED** to future phase (too problematic via PTP)

### Phase 5: Frontend WebUI (Vue 3)
- Set up Vue 3 + Vite + TailwindCSS
- Responsive layout with live view canvas
- Settings control panel using **sliders and buttons** (not dropdowns)
- Live View component with:
  - Aspect ratio handling (letterbox)
  - Zoom/pan controls
  - Grid overlay toggle
  - Real-time histogram
- Capture button with visual feedback (state machine: IDLE → CAPTURING → DONE)
- Last capture preview with EXIF data
- File browser/gallery for captured images
- Mode dial warning banner
- **Keyboard shortcuts**: Space = capture, H = histogram, G = grid
- **Accessibility**: ARIA labels, focus indicators, touch targets

### Phase 6: Time-lapse System
- Research D500 built-in intervalometer (more reliable than software)
- Fallback: Software intervalometer with documented ±500ms jitter
- Time-lapse configuration UI:
  - Interval selector with minimum recommendations (2s for RAW, 1s for JPEG)
  - Total frames OR duration mode
  - Disk space estimation and warning
  - Battery level check before starting
- API endpoints:
  - `POST /api/timelapse/start` - Start with config
  - `POST /api/timelapse/stop` - Stop running
  - `GET /api/timelapse/status` - Progress + ETA
- WebSocket progress updates
- Video generation via FFmpeg subprocess (not ffmpeg-python)
- Post-processing UI with codec selection and progress bar

### Phase 7: Error Handling & Polish
- Comprehensive disconnection handling with auto-reconnect
- Error toasts and status banners in UI
- Structured logging with structlog
- Connection quality indicator
- Session management (track shooting sessions)
- API documentation (auto-generated by FastAPI)
- Integration tests with mocked camera

## Key Features

### Controllable Settings (via PTP)
| Setting | Support Level | Notes |
|---------|---------------|-------|
| ISO | Full (100-51200) | Extended modes (64, 102400) may fail |
| Aperture | Mode-dependent | Only works in A/M modes |
| Shutter Speed | Mode-dependent | Only works in S/M modes |
| Exposure Mode | Read-only | Must be set via mode dial |
| Focus Mode | AF-S/AF-C/MF | Focus point selection NOT supported |
| White Balance | Presets only | Kelvin adjustment may fail |
| Image Format | Single format | RAW+JPEG is unreliable |
| Metering Mode | Full | Matrix/Center/Spot/etc |

### Live View
- Real-time preview at **5-10 FPS** (USB 2.0 bandwidth limited)
- Binary WebSocket streaming (not base64)
- Keep-alive pings every 30 seconds (camera times out at 60s)
- Automatic pause during capture operations
- Resolution: ~1280x850 (camera-determined)

### Media Transfer
- Automatic download after capture (with 2s delay for card write)
- Configurable output folder (via Docker volume mount)
- File listing with thumbnails
- EXIF metadata display
- Gallery browser

### Time-lapse
- Configurable interval (minimum 2s for RAW, 1s for JPEG)
- Set by total duration OR frame count
- Disk space estimation before starting
- Real-time progress via WebSocket (frames, ETA, completion time)
- Video generation via FFmpeg (H.264/H.265/ProRes)
- Dedicated folder per session
- **Known limitation**: Software intervalometer has ±500ms jitter

### UI Features
- Vue 3 reactive interface
- Histogram overlay on live view
- Rule-of-thirds grid toggle
- Keyboard shortcuts (Space=capture, H=histogram, G=grid)
- Mobile-responsive layout
- Dark theme optimized for photography

## Docker Deployment

**Important**: Do NOT use `--privileged` mode. Use device passthrough instead.

```bash
# Run the application
docker-compose up -d

# With custom output folder
OUTPUT_PATH=/home/user/photos docker-compose up -d
```

### docker-compose.yml
```yaml
version: '3.8'
services:
  camera-app:
    build: .
    ports:
      - "8000:8000"
    devices:
      - /dev/bus/usb:/dev/bus/usb  # USB passthrough
    volumes:
      - ${OUTPUT_PATH:-./output}:/app/output
      - /var/run/dbus:/var/run/dbus:ro  # For udev events
    environment:
      - OUTPUT_PATH=/app/output
      - LOG_LEVEL=INFO
    # NO privileged: true
```

### USB Permissions (Host Setup)
```bash
# Create udev rule for Nikon cameras
sudo tee /etc/udev/rules.d/99-nikon.rules << EOF
SUBSYSTEM=="usb", ATTRS{idVendor}=="04b0", MODE="0666"
EOF
sudo udevadm control --reload-rules
```

## Critical Files to Create

### Backend (Priority Order)
1. `backend/camera/state.py` - CameraState enum (IDLE/LIVEVIEW/CAPTURING)
2. `backend/camera/controller.py` - State machine + threading.Lock + keep-alive
3. `backend/camera/keepalive.py` - 30-second ping mechanism
4. `backend/camera/exceptions.py` - Comprehensive error hierarchy
5. `backend/camera/settings.py` - Settings discovery with mode-aware behavior
6. `backend/camera/live_view.py` - Binary frame streaming at 5-10 FPS
7. `backend/camera/capture.py` - Photo capture with 2s post-capture delay
8. `backend/camera/timelapse.py` - Intervalometer with jitter documentation
9. `backend/main.py` - FastAPI app with WebSocket routes
10. `backend/config.py` - Pydantic settings with all tunables

### Frontend (Vue 3)
1. `frontend/src/components/LiveView.vue` - Canvas + histogram + grid
2. `frontend/src/components/SettingsPanel.vue` - Sliders/buttons UI
3. `frontend/src/components/CaptureControls.vue` - Capture button + feedback
4. `frontend/src/components/Gallery.vue` - File browser
5. `frontend/src/composables/useWebSocket.js` - WebSocket connection management
6. `frontend/src/stores/camera.js` - Pinia state store

### Infrastructure
1. `docker/Dockerfile` - Multi-stage build with pinned versions
2. `docker/docker-compose.yml` - Non-privileged USB passthrough
3. `docker/udev/99-nikon.rules` - USB permissions

## Verification Plan

### Phase 1 Verification
1. **Camera Detection**: `docker-compose up`, check `/api/camera/status` returns D500 info
2. **Keep-alive**: Leave camera connected for 2+ minutes, verify no timeout disconnect
3. **Reconnection**: Unplug USB, verify error shown, replug, verify auto-reconnect

### Phase 2 Verification
1. **Settings Discovery**: `/api/settings` returns all available settings
2. **Mode Dependency**: Set mode dial to P, verify aperture is read-only. Set to M, verify writable.
3. **ISO Change**: Change ISO via API, confirm change on camera LCD

### Phase 3 Verification
1. **Live View Start**: Enable live view, verify frames arrive at 5-10 FPS
2. **Frame Rate**: Check console logs show consistent frame delivery
3. **Timeout Recovery**: Wait 50 seconds, verify keep-alive prevents disconnect

### Phase 4 Verification
1. **Photo Capture**: Take photo, verify file appears in `/app/output` within 5 seconds
2. **Live View Pause**: Verify live view stops during capture, resumes after
3. **File Integrity**: Downloaded file opens correctly in image viewer

### Phase 5 Verification
1. **UI Load**: Open browser, verify Vue app loads with live view
2. **Settings UI**: Change ISO via slider, confirm change reflects on camera
3. **Keyboard**: Press Space, verify capture triggers
4. **Histogram**: Enable histogram, verify it updates in real-time

### Phase 6 Verification
1. **Time-lapse Config**: Set 5 frames, 2s interval, verify disk space estimate
2. **Time-lapse Run**: Start, verify progress updates every 2 seconds
3. **Video Generation**: After completion, generate video, verify valid MP4

### Phase 7 Verification
1. **Stress Test**: Run for 30+ minutes, verify no memory leaks or disconnects
2. **Error Handling**: Unplug during capture, verify graceful error and recovery

## Dependencies

### Python (requirements.txt) - PIN EXACT VERSIONS
```
# Web Framework
fastapi==0.109.2
uvicorn[standard]==0.27.1
python-multipart==0.0.9

# Camera Control - PIN EXACT VERSION
gphoto2==2.5.0

# Data Validation & Config
pydantic==2.6.1
pydantic-settings==2.1.0

# Utilities
aiofiles==23.2.1
pillow==10.2.0            # Thumbnails
tenacity==8.2.3           # Retry logic for reconnection
structlog==24.1.0         # Structured logging

# Testing
pytest==8.0.0
pytest-asyncio==0.23.4
httpx==0.26.0

# NOTE: ffmpeg-python is DEAD - use subprocess instead
```

### Frontend (package.json)
```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "pinia": "^2.1.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "tailwindcss": "^3.4.0"
  }
}
```

### System (in Dockerfile) - PIN UBUNTU VERSION
```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    libgphoto2-6=2.5.27-1ubuntu7 \
    libgphoto2-dev=2.5.27-1ubuntu7 \
    ffmpeg=7:5.1.2-1ubuntu2 \
    python3.11
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Live View timeout at 60s | HIGH | CRITICAL | Keep-alive pings every 30s (Phase 1) |
| Settings silently fail (wrong mode) | HIGH | HIGH | Mode dial warning in UI + README |
| 15 FPS unachievable | CERTAIN | MEDIUM | Document 5-10 FPS as target |
| RAW+JPEG unreliable | MEDIUM | MEDIUM | Recommend single format; document as best-effort |
| Video recording corruption | HIGH | CRITICAL | **Defer video to future phase** |
| USB disconnect during capture | MEDIUM | HIGH | Retry logic + graceful error handling |
| Time-lapse interval jitter | MEDIUM | MEDIUM | Document ±500ms; research D500 intervalometer |
| gphoto2 version incompatibility | MEDIUM | HIGH | Pin exact versions in Docker |

---

## Known Limitations (Document in README)

1. **Mode Dial**: Camera MUST be set to P, A, S, or M mode. Auto/Scene modes cause settings to silently fail.
2. **Live View FPS**: Maximum 5-10 FPS due to USB 2.0 bandwidth. Not suitable for real-time video preview.
3. **Focus Points**: Cannot remotely select focus points. Only AF mode (AF-S/AF-C/MF) is controllable.
4. **Video Recording**: Not supported in initial release due to PTP reliability issues.
5. **RAW+JPEG**: May capture only one format. Single format recommended.
6. **Time-lapse Accuracy**: Software intervalometer has ±500ms jitter per frame.
7. **Extended ISO**: ISO 64 and 102400+ may not be settable via remote.
8. **White Balance Kelvin**: Only presets work reliably; numeric Kelvin adjustment may fail.
