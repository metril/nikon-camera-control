# Touchscreen kiosk: cage (Wayland kiosk compositor) + Chromium on the host's HDMI output.
# The host needs no desktop. No env-based options: the URL is fixed, configure in the web UI.
FROM debian:trixie-slim
ARG TARGETARCH
RUN apt-get update \
 && pkgs="cage seatd chromium curl ca-certificates mesa-va-drivers libgl1-mesa-dri libegl1 \
      fonts-noto-core libinput10 libudev1 libxkbcommon0 xkb-data wlr-randr util-linux" \
 && if [ "$TARGETARCH" = "amd64" ]; then pkgs="$pkgs intel-media-va-driver"; fi \
 && apt-get install -y --no-install-recommends $pkgs \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r seat \
 && useradd -r -m -g seat -s /usr/sbin/nologin kiosk
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh
# Starts as root only to run seatd (it opens /dev/dri and /dev/input for the compositor);
# cage and Chromium run as the unprivileged "kiosk" user.
ENTRYPOINT ["/entrypoint.sh"]
