#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
KIND="${1:-update}"
VERSION="${APP_VERSION:-1.1}"

if [[ "$KIND" != "install" && "$KIND" != "update" ]]; then
  echo "Usage: bash deploy/raspberry-pi/package.sh [install|update]" >&2
  exit 2
fi

if [[ ! "$VERSION" =~ ^[0-9]+([.][0-9]+)*$ ]]; then
  echo "APP_VERSION must contain numbers separated by dots, for example 1.1." >&2
  exit 2
fi

if [[ ! -f "$ROOT_DIR/frontend/build/index.html" ]]; then
  echo "Frontend build is missing. Build it first with: REACT_APP_BACKEND_URL= yarn --cwd frontend build" >&2
  exit 1
fi

BUILD_ID="$(date -u +%Y%m%d-%H%M%S)-$$"
ARCHIVE="$SCRIPT_DIR/rom-translator-${KIND}-v${VERSION}-${BUILD_ID}.tar.gz"

tar -czf "$ARCHIVE" -C "$ROOT_DIR" \
  --transform='s,^,rom-translator/,' \
  backend/server.py \
  backend/charmaps.py \
  backend/text_extract.py \
  backend/requirements-pi.txt \
  frontend/build \
  deploy/raspberry-pi/install.sh \
  deploy/raspberry-pi/package.sh \
  deploy/raspberry-pi/rom-translator.nginx.conf \
  deploy/raspberry-pi/rom-translator.service \
  deploy/raspberry-pi/README.md

printf '%s\n' "$ARCHIVE"
