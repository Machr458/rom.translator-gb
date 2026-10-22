#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
KIND="${1:-update}"
VERSION="${APP_VERSION:-1.2}"

if [[ "$KIND" != "install" && "$KIND" != "update" ]]; then
  echo "Usage: bash deploy/raspberry-pi/package.sh [install|update]" >&2
  exit 2
fi

if [[ ! "$VERSION" =~ ^[0-9]+([.][0-9]+)*$ ]]; then
  echo "APP_VERSION must contain numbers separated by dots, for example 1.2." >&2
  exit 2
fi

REACT_APP_BACKEND_URL= REACT_APP_VERSION="$VERSION" yarn --cwd "$ROOT_DIR/frontend" build

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
