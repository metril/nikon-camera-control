# Nikon D500 Camera Control

A web-based application to control a Nikon D500 camera via USB, featuring real-time Live View, full settings control, media capture/transfer, and time-lapse creation.

---

## IMPORTANT: Camera Setup Required

### Mode Dial Position

**The camera mode dial MUST be set to P, A, S, or M for remote control to work.**

Settings changes will silently fail if the mode dial is in:
- Auto mode
- Scene modes (Portrait, Landscape, etc.)
- Effects modes

Always verify the mode dial position before starting a remote session.

### USB Connection

1. Use a high-quality USB cable (preferably the one that came with your camera)
2. Connect directly to a USB port (avoid unpowered hubs)
3. Ensure the camera is powered on before connecting
4. Wait for the camera to be recognized before starting the application

---

## Features

### Camera Control
- **Settings**: ISO, Aperture, Shutter Speed, Focus Mode, White Balance, Image Format, Metering Mode
- **Live View**: Real-time preview at 5-10 FPS (USB 2.0 bandwidth limited)
- **Photo Capture**: Remote shutter with automatic file transfer
- **Time-lapse**: Interval shooting with video generation

### Web Interface
- Vue 3 reactive UI with TailwindCSS
- Live histogram overlay
- Keyboard shortcuts (Space = capture, H = histogram, G = grid)
- File browser/gallery
- Mobile-responsive design

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Nikon D500 camera with USB cable
- Linux host (Ubuntu/Debian recommended)

### 1. Set Up USB Permissions

```bash
# Copy udev rules to allow USB access
sudo cp docker/udev/99-nikon.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 2. Start the Application

```bash
# Start the container
docker-compose -f docker/docker-compose.yml up -d

# View logs
docker-compose -f docker/docker-compose.yml logs -f
```

### 3. Access the Web Interface

Open http://localhost:8000 in your browser.

### 4. Set Output Folder

```bash
# Specify where captured photos should be saved
OUTPUT_PATH=/home/user/photos docker-compose -f docker/docker-compose.yml up -d
```

---

## Known Limitations

Please be aware of these limitations before using:

| Limitation | Description |
|------------|-------------|
| **Mode Dial** | Camera MUST be in P/A/S/M mode. Other modes cause settings to fail silently. |
| **Live View FPS** | Maximum 5-10 FPS due to USB 2.0 bandwidth. Not suitable for video preview. |
| **Focus Points** | Cannot select focus points remotely. Only AF mode (AF-S/AF-C/MF) is controllable. |
| **Video Recording** | Not supported in this version due to PTP protocol reliability issues. |
| **RAW+JPEG** | May capture only one format. Single format recommended for reliability. |
| **Time-lapse Accuracy** | Software intervalometer has ±500ms jitter per frame. |
| **Extended ISO** | ISO 64 and 102400+ may not be settable via remote control. |
| **White Balance Kelvin** | Only presets work reliably. Numeric Kelvin adjustment may fail. |

---

## API Reference

### Health Check
```
GET /api/health
```

### Camera Status
```
GET /api/camera/status
```

### Connect/Disconnect
```
POST /api/camera/connect
POST /api/camera/disconnect
```

### Camera Summary
```
GET /api/camera/summary
```

### WebSocket Events
```
WS /ws/events
```

Receive real-time updates for:
- Camera state changes
- Capture completion
- Time-lapse progress
- Error notifications

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTPUT_PATH` | `/app/output` | Directory for captured media |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CAMERA_KEEPALIVE_INTERVAL` | `30` | Seconds between keep-alive pings |
| `LIVEVIEW_TARGET_FPS` | `8` | Target frames per second for live view |

### Docker Compose Override

Create `docker-compose.override.yml` for local customizations:

```yaml
version: '3.8'
services:
  nikon-camera-control:
    volumes:
      - /path/to/your/photos:/app/output
    environment:
      - LOG_LEVEL=DEBUG
```

---

## Troubleshooting

### Camera Not Detected

1. Check USB cable connection
2. Ensure camera is powered on
3. Verify mode dial is in P/A/S/M
4. Check udev rules are installed:
   ```bash
   ls -la /etc/udev/rules.d/99-nikon.rules
   ```
5. Restart udev:
   ```bash
   sudo udevadm control --reload-rules
   ```

### Settings Not Applying

1. **Check mode dial** - Must be in P, A, S, or M
2. Some settings are mode-dependent:
   - Aperture only works in A or M mode
   - Shutter speed only works in S or M mode
3. Auto-ISO may override manual ISO settings

### Live View Freezing

1. The camera times out after 60 seconds without commands
2. The application sends keep-alive pings every 30 seconds
3. If live view freezes, the keep-alive may have failed
4. Disconnect and reconnect the camera

### Container USB Access

If the container cannot access the camera:

```bash
# Check if camera is detected on host
lsusb | grep Nikon

# Verify USB device permissions
ls -la /dev/bus/usb/

# Restart container with debug
docker-compose -f docker/docker-compose.yml down
docker-compose -f docker/docker-compose.yml up
```

---

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests

```bash
pytest tests/ -v
```

### Building Frontend

```bash
cd frontend
npm install
npm run build
```

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python 3.11 + FastAPI |
| Camera Control | python-gphoto2 (libgphoto2 bindings) |
| Live View | WebSocket (binary frames) |
| Frontend | Vue 3 + TailwindCSS |
| Video Encoding | FFmpeg |
| Deployment | Docker |

---

## License

MIT License - see LICENSE file for details.

---

## Acknowledgments

- [libgphoto2](http://gphoto.org/) - Camera control library
- [python-gphoto2](https://github.com/jim-easterbrook/python-gphoto2) - Python bindings
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
