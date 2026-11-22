# Nikon D500 camera controller. Build from the repo root:
#   docker build -f docker/Dockerfile -t nikon-camera-control:dev .
# No environment-based app configuration: everything is set in the web UI (data/config.json).

# --- Stage 1: frontend bundle ------------------------------------------------
# The bundle is arch-independent: always build it on the native build platform (no QEMU).
FROM --platform=$BUILDPLATFORM oven/bun:1.3.10-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

# --- Stage 2: Python venv (gphoto2 wheels bundle libgphoto2; no compiler needed) ---
FROM python:3.12.13-slim-bookworm AS venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# --- Stage 3: runtime ---------------------------------------------------------
FROM python:3.12.13-slim-bookworm
# ffmpeg renders time-lapse videos; libusb is loaded by the bundled libgphoto2 port driver.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
# Fixed ids so host volume ownership is predictable. plugdev (gid 46 on Debian/Ubuntu)
# is the group the udev rule grants USB access to.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --groups plugdev --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/output \
    && chown -R app:app /app
COPY --from=venv /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --chown=app:app backend/ ./backend/
COPY --from=frontend --chown=app:app /app/frontend/dist ./frontend/dist/
USER app
VOLUME ["/app/data", "/app/output"]
EXPOSE 8000
# Fails on any non-2xx (urlopen raises HTTPError) or connection error.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u,sys; sys.exit(0 if 200 <= u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5).status < 300 else 1)"]
CMD ["uvicorn", "backend.asgi:create", "--factory", "--host", "0.0.0.0", "--port", "8000"]
