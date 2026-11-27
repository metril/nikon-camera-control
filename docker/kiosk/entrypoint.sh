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

# /kiosk-profile is a named volume (root-owned when new): the profile keeps the API key and prefs across restarts.
mkdir -p /tmp/xdg /kiosk-profile && chown kiosk:seat /tmp/xdg /kiosk-profile && chmod 700 /tmp/xdg

PROFILE=/kiosk-profile/chromium
CHILD=
WATCHERS=

# Auto scale from the connected screen: EDID bytes 21/22 are width/height in cm, the first
# line of "modes" is the resolution. scale = clamp(round to 0.25 of ppi/96, 1, 2); 1 if unknown.
auto_scale() {
  for d in /sys/class/drm/card*-*; do
    [ "$(cat "$d/status" 2>/dev/null)" = connected ] || continue
    res=$(head -n 1 "$d/modes" 2>/dev/null)
    cm=$(od -An -tu1 -j21 -N2 "$d/edid" 2>/dev/null)
    [ -n "$res" ] && [ -n "$cm" ] || continue
    # shellcheck disable=SC2086
    set -- $cm
    awk -v res="$res" -v w="$1" -v h="$2" 'BEGIN {
      split(res, r, "x")
      if (w < 1 || h < 1 || r[1] < 1 || r[2] < 1) { print 1; exit }
      ppi = sqrt(r[1]^2 + r[2]^2) / (sqrt(w^2 + h^2) / 2.54)
      s = int(ppi / 96 * 4 + 0.5) / 4
      if (s < 1) s = 1; if (s > 2) s = 2
      print s
    }'
    return
  done
  echo 1
}

# Setting from the web UI ("auto" or a number), read once.
fetch_setting() {
  curl -fsS --max-time 5 -N "$APP/api/v1/kiosk/scale" 2>/dev/null | head -n 1 | sed 's/^data: *//'
}
resolve_scale() {
  case "$1" in
    1|1.25|1.5|2) echo "$1" ;;
    *) auto_scale ;;
  esac
}

# Event-driven watchers: each TERMs cage on a change and the loop below relaunches it.
kill_cage() { pkill -TERM -x cage 2>/dev/null; }
watch_scale() {
  while true; do
    until curl -fsS -o /dev/null "$APP/api/v1/health"; do sleep 2; done
    curl -fsSN --speed-limit 1 --speed-time 45 "$APP/api/v1/kiosk/scale" 2>/dev/null | while IFS= read -r line; do
      case "$line" in  # ": ping" heartbeat comments and blank lines fall through ignored
        "data: "*)
          want=$(resolve_scale "${line#data: }")
          # Also skips the initial event, which equals the scale Chromium started with.
          [ "$want" = "$(cat /tmp/kiosk-scale 2>/dev/null)" ] && continue
          echo "kiosk: scale -> $want"; kill_cage ;;
      esac
    done
    sleep 2
  done
}
# udev netlink events don't reach this netns, so libinput never sees hotplug. udevd writes a
# device's db entry only after it has finished processing it: a new c13:* entry means it is ready.
watch_input() {
  inotifywait -m -q -e create -e moved_to -e delete --format '%f' /run/udev/data 2>/dev/null |
    while IFS= read -r f; do
      # One replug adds several c13:* entries (event, mouse, ...): restart cage once, 2 s after the first.
      case "$f" in c13:*)
        echo "kiosk: input device change ($f)"
        [ -e /tmp/kiosk-restart-pending ] && continue
        touch /tmp/kiosk-restart-pending
        (sleep 2; rm -f /tmp/kiosk-restart-pending; kill_cage) & ;;
      esac
    done
}

# PID 1 is this shell: forward TERM so Chromium shuts down cleanly (and drops its profile lock).
cleanup() {
  # shellcheck disable=SC2086
  [ -n "$WATCHERS" ] && kill $WATCHERS 2>/dev/null
  pkill -x curl 2>/dev/null; pkill -x inotifywait 2>/dev/null
  kill -TERM "$CHILD" 2>/dev/null; wait "$CHILD" 2>/dev/null
  exit 0
}
trap cleanup TERM INT

SCALE=$(resolve_scale "$(fetch_setting)")
echo "$SCALE" > /tmp/kiosk-scale
echo "kiosk: display scale $SCALE"
watch_scale & WATCHERS="$!"
watch_input & WATCHERS="$WATCHERS $!"

while true; do
  # A recreated container has a new hostname, so Chromium sees the old Singleton* lock as foreign and refuses the profile.
  rm -f "$PROFILE"/Singleton*
  SCALE=$(resolve_scale "$(fetch_setting)")
  echo "$SCALE" > /tmp/kiosk-scale
  setpriv --reuid kiosk --regid seat --keep-groups env \
    XDG_RUNTIME_DIR=/tmp/xdg HOME=/kiosk-profile LIBSEAT_BACKEND=seatd WLR_NO_HARDWARE_CURSORS=1 \
    cage -s -- chromium --kiosk --no-sandbox --ozone-platform=wayland \
      --enable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL --touch-events=enabled --force-device-scale-factor="$SCALE" \
      --noerrdialogs --disable-session-crashed-bubble --no-first-run --password-store=basic \
      --disk-cache-dir=/tmp/chromium-cache \
      --user-data-dir="$PROFILE" "$APP/?layout=touch" &
  CHILD=$!
  wait "$CHILD"
  echo "kiosk: chromium exited, restarting in 3s"; sleep 3
done
