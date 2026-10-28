#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
KIND="${1:-update}"
VERSION_FILE="$SCRIPT_DIR/VERSION"

if [[ -n "${APP_VERSION:-}" ]]; then
  VERSION="$APP_VERSION"
elif [[ -f "$VERSION_FILE" ]]; then
  VERSION="$(<"$VERSION_FILE")"
else
  VERSION=1.2
fi

if [[ "$KIND" != "install" && "$KIND" != "update" ]]; then
  echo "Usage: bash deploy/raspberry-pi/package.sh [install|update]" >&2
  exit 2
fi

if [[ ! "$VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  echo "Version must use major.minor format, for example 1.2." >&2
  exit 2
fi

if [[ "$KIND" == "update" && -z "${APP_VERSION:-}" ]]; then
  VERSION="${BASH_REMATCH[1]}.$((${BASH_REMATCH[2]} + 1))"
fi

REACT_APP_BACKEND_URL= REACT_APP_VERSION="$VERSION" yarn --cwd "$ROOT_DIR/frontend" build

ARCHIVE="$SCRIPT_DIR/rom-translator-${KIND}-v${VERSION}.tar.gz"

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
  deploy/raspberry-pi/rom-translator-ngrok.service \
  deploy/raspberry-pi/rom-translator.service \
  deploy/raspberry-pi/README.md

printf '%s\n' "$VERSION" > "$VERSION_FILE"

printf '%s\n' "$ARCHIVE"
