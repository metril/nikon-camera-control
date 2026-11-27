# Touchscreen kiosk: cage (Wayland kiosk compositor) + Chromium on the host's HDMI output.
# The host needs no desktop. No env-based options: the URL is fixed, configure in the web UI.

# cage 0.2.0 (Debian trixie's version) plus a patch adding wlr-output-power-management-v1 (DPMS),
# built against trixie's wlroots 0.18. No release of cage has it.
FROM debian:trixie-slim AS cage-build
ARG CAGE_VERSION=0.2.0
ARG CAGE_SHA256=9d3f659e0f19636a958f9e1bf4d22268d7e2705d7e2989888401ec443c1cb6c3
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl patch meson ninja-build pkgconf gcc \
      libwlroots-0.18-dev libwayland-dev wayland-protocols libxkbcommon-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL -o cage.tgz "https://github.com/cage-kiosk/cage/archive/refs/tags/v${CAGE_VERSION}.tar.gz" \
 && echo "${CAGE_SHA256}  cage.tgz" | sha256sum -c - \
 && tar xzf cage.tgz --strip-components=1 && rm cage.tgz
# Protocol XML from wlroots 0.18.2 (protocol/); its installed header needs the generated server header.
COPY wlr-output-power-management-unstable-v1.xml /src/
COPY cage-output-power.patch /tmp/
RUN patch -p1 < /tmp/cage-output-power.patch \
 && meson setup build --prefix=/usr/local --buildtype=release 2>&1 | tail -5 \
 && ninja -C build && DESTDIR=/out ninja -C build install && strip /out/usr/local/bin/cage

FROM debian:trixie-slim
ARG TARGETARCH
# "cage" is installed only to pull its runtime libs (wlroots 0.18, ...); its binary is replaced below.
RUN apt-get update \
 && pkgs="cage wlopm seatd chromium curl ca-certificates mesa-va-drivers libgl1-mesa-dri libegl1 \
      fonts-noto-core libinput10 libudev1 libxkbcommon0 xkb-data wlr-randr util-linux inotify-tools" \
 && if [ "$TARGETARCH" = "amd64" ]; then pkgs="$pkgs intel-media-va-driver"; fi \
 && apt-get install -y --no-install-recommends $pkgs \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r seat \
 && useradd -r -m -g seat -s /usr/sbin/nologin kiosk
COPY --from=cage-build /out/usr/local/bin/cage /usr/bin/cage
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh
# Starts as root only to run seatd (it opens /dev/dri and /dev/input for the compositor);
# cage and Chromium run as the unprivileged "kiosk" user.
ENTRYPOINT ["/entrypoint.sh"]
