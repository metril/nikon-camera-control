#!/usr/bin/env bash
# Fails unless backend __version__, frontend/package.json version and the compose image tag agree
# (and, when given a tag such as v0.2.0 as $1, unless the tag is "v" + that version).
set -euo pipefail
cd "$(dirname "$0")/.."
py=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' backend/__init__.py)
js=$(sed -n 's/^  "version": "\(.*\)",$/\1/p' frontend/package.json)
img=$(sed -n 's|^ *image: ghcr.io/metril/nikon-camera-control:\(.*\)$|\1|p' docker/compose.yaml)
echo "backend=$py frontend=$js compose=$img tag=${1:-<none>}"
[ -n "$py" ] || { echo "no __version__ found"; exit 1; }
[ "$py" = "$js" ] && [ "$py" = "$img" ] || { echo "version mismatch"; exit 1; }
[ -z "${1:-}" ] || [ "$1" = "v$py" ] || { echo "tag $1 != v$py"; exit 1; }
