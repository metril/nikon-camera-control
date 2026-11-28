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
# Device token the app writes to the read-only kiosk-auth volume. The page trades it for a kiosk
# session via the URL fragment (#pair=), which the browser never sends to the server.
TOKEN_FILE=/kiosk-auth/kiosk-token
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
# Panel power (DPMS) via wlopm, only while cage runs. Failures are ignored.
display_power() {
  pgrep -x cage >/dev/null 2>&1 || return 0
  setpriv --reuid kiosk --regid seat --keep-groups env XDG_RUNTIME_DIR=/tmp/xdg WAYLAND_DISPLAY=wayland-0 \
    wlopm "--$1" '*' >/dev/null 2>&1 || true
}
# Brightness (VCP 0x10) saved while dimmed: on the persistent volume, so a container restart
# while asleep still restores it. /tmp is tmpfs.
BRIGHT_FILE=/kiosk-profile/ddc-brightness
# Last DPMS state (on|off); a relaunched cage applies it instead of always lighting the panel.
DPMS_FILE=/tmp/kiosk-dpms
# ddcutil needs the i2c nodes; the compose cgroup rule allows c 89:* but creates none.
for n in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  [ -e "/dev/i2c-$n" ] || mknod "/dev/i2c-$n" c 89 "$n" 2>/dev/null || true
done
# Dim: remember the current brightness (only if not already dimmed), then set it to 0.
# No DDC (or a failing monitor) just leaves the black overlay. Failures are ignored.
dim_on() {
  if [ ! -s "$BRIGHT_FILE" ]; then
    cur=$(ddcutil --nousb getvcp 10 --brief 2>/dev/null | awk '$1 == "VCP" && $3 == "C" {print $4; exit}')
    case "$cur" in ''|*[!0-9]*|0) cur= ;; esac
    [ -n "$cur" ] && echo "$cur" > "$BRIGHT_FILE"
  fi
  ddcutil --nousb setvcp 10 0 >/dev/null 2>&1 || true
}
dim_off() {
  [ -s "$BRIGHT_FILE" ] || return 0
  ddcutil --nousb setvcp 10 "$(cat "$BRIGHT_FILE")" >/dev/null 2>&1 && rm -f "$BRIGHT_FILE"
  return 0
}
# Applies the whole wanted state (idempotent), so a mode switch while asleep undoes the old action.
# $1 on|off, $2 black|dim|off. Serialized by a lock; the stream loop calls it one event at a time.
apply_display() {
  dpms=on dim=0
  if [ "$1" = off ]; then
    case "$2" in off) dpms=off ;; dim) dim=1 ;; esac
  fi
  (
    flock 9
    echo "$dpms" > "$DPMS_FILE"
    display_power "$dpms"
    if [ "$dim" = 1 ]; then dim_on; else dim_off; fi
  ) 9>/tmp/kiosk-display.lock
}
# Follows the app's display state ("data: on" / "data: off <black|dim|off>"), same stream format as
# the scale one. A 404 (app without the endpoint) yields no data: back off 30 s instead of 2 s.
watch_display() {
  while true; do
    until curl -fsS -o /dev/null "$APP/api/v1/health"; do sleep 2; done
    rm -f /tmp/kiosk-display-seen
    curl -fsSN --speed-limit 1 --speed-time 45 "$APP/api/v1/kiosk/display" 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        "data: on"|"data: off"|"data: off "*)
          touch /tmp/kiosk-display-seen
          echo "kiosk: display ${line#data: }"
          # shellcheck disable=SC2086
          set -- ${line#data: }
          mode=${2:-black}
          case "$mode" in black|dim|off) ;; *) mode=black ;; esac
          apply_display "$1" "$mode" ;;
      esac
    done
    if [ -e /tmp/kiosk-display-seen ]; then sleep 2; else sleep 30; fi
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

# Waits (up to ~60 s) for the token file, then prints its first line. Empty output = no token
# (app without kiosk auth): the kiosk still starts, unpaired.
# Trade the device token for a single-use 30 s pairing code, so the token itself never reaches
# Chromium's argv, URL or history (nor any argv here: it goes to curl through stdin).
pair_code() {
  [ -n "$(read_token)" ] || return 0
  { printf '{"token":"'; head -n 1 "$TOKEN_FILE" | tr -dc 'A-Za-z0-9_-'; printf '"}'; } |
    curl -fsS --max-time 10 -H 'Content-Type: application/json' --data-binary @- \
      "$APP/api/v1/auth/kiosk/code" 2>/dev/null |
    sed -n 's/.*"code" *: *"\([A-Za-z0-9_-]*\)".*/\1/p'
}
read_token() {
  n=0
  until [ -s "$TOKEN_FILE" ] || [ "$n" -ge 30 ]; do
    [ "$n" -eq 0 ] && echo "kiosk: waiting for $TOKEN_FILE ..." >&2
    n=$((n + 1)); sleep 2
  done
  head -n 1 "$TOKEN_FILE" 2>/dev/null | tr -d '\r\n '
}
# Token rotation rewrites the file (possibly via rename): restart cage so the page pairs again.
# Watches the directory, since a rename replaces the file's inode.
watch_token() {
  while true; do
    inotifywait -m -q -e close_write -e moved_to -e create -e delete --format '%f' /kiosk-auth 2>/dev/null |
      while IFS= read -r f; do
        [ "$f" = kiosk-token ] || continue
        [ -e /tmp/kiosk-token-pending ] && continue
        touch /tmp/kiosk-token-pending
        (sleep 1; rm -f /tmp/kiosk-token-pending; echo "kiosk: token changed"; kill_cage) &
      done
    sleep 2
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
watch_display & WATCHERS="$WATCHERS $!"
watch_token & WATCHERS="$WATCHERS $!"

while true; do
  # A recreated container has a new hostname, so Chromium sees the old Singleton* lock as foreign and refuses the profile.
  rm -f "$PROFILE"/Singleton*
  SCALE=$(resolve_scale "$(fetch_setting)")
  echo "$SCALE" > /tmp/kiosk-scale
  START_URL="$APP/?layout=touch&kiosk=1"
  CODE=$(pair_code)
  [ -n "$CODE" ] && START_URL="$START_URL#pair=$CODE"
  # Scale the compositor output before Chromium starts (it then renders natively at that scale).
  # Not --force-device-scale-factor: under Wayland it mis-sizes the window (part of the screen
  # stays black). Changing the output scale under a running Chromium breaks touch, hence the relaunch.
  setpriv --reuid kiosk --regid seat --keep-groups env \
    XDG_RUNTIME_DIR=/tmp/xdg HOME=/kiosk-profile LIBSEAT_BACKEND=seatd WLR_NO_HARDWARE_CURSORS=1 \
    KIOSK_SCALE="$SCALE" PROFILE="$PROFILE" START_URL="$START_URL" \
    cage -s -- sh -c '
      if [ "$(cat /tmp/kiosk-dpms 2>/dev/null)" = off ]; then wlopm --off "*"; else wlopm --on "*"; fi >/dev/null 2>&1
      for o in $(wlr-randr | awk "/^[^ ]/ {print \$1}"); do wlr-randr --output "$o" --scale "$KIOSK_SCALE"; done
      exec chromium --kiosk --no-sandbox --ozone-platform=wayland \
        --enable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL --touch-events=enabled \
        --noerrdialogs --disable-session-crashed-bubble --no-first-run --password-store=basic \
        --disk-cache-dir=/tmp/chromium-cache \
        --user-data-dir="$PROFILE" "$START_URL"' &
  CHILD=$!
  wait "$CHILD"
  echo "kiosk: chromium exited, restarting in 3s"; sleep 3
done
