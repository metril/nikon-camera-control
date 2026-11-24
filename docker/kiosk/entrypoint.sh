#!/bin/sh
# seatd runs as root (brokers device access); cage + Chromium run as user "kiosk" via setpriv.
set -u
APP=http://nikon-camera-control:8000

until curl -fsS -o /dev/null "$APP/api/v1/health"; do
  echo "kiosk: waiting for $APP ..."; sleep 2
done

export LIBSEAT_BACKEND=seatd
# No VT in a container: run the seat without VT binding, or cage times out waiting for an active session.
SEATD_VTBOUND=0 seatd -g seat &
for _ in 1 2 3 4 5 6 7 8 9 10; do [ -S /run/seatd.sock ] && break; sleep 0.5; done

mkdir -p /tmp/xdg /tmp/chromium && chown kiosk:seat /tmp/xdg /tmp/chromium && chmod 700 /tmp/xdg

while true; do
  setpriv --reuid kiosk --regid seat --keep-groups env \
    XDG_RUNTIME_DIR=/tmp/xdg HOME=/tmp/chromium LIBSEAT_BACKEND=seatd WLR_NO_HARDWARE_CURSORS=1 \
    cage -s -- chromium --kiosk --no-sandbox --ozone-platform=wayland \
      --enable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL --touch-events=enabled \
      --noerrdialogs --disable-session-crashed-bubble --no-first-run --password-store=basic \
      --user-data-dir=/tmp/chromium "$APP/?layout=touch"
  echo "kiosk: chromium exited, restarting in 3s"; sleep 3
done
