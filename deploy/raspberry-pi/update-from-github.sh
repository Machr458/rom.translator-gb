#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="Machr458/rom.translator-gb"
API_URL="https://api.github.com/repos/${REPOSITORY}/releases/latest"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run this updater with sudo: curl -fsSL https://raw.githubusercontent.com/${REPOSITORY}/main/deploy/raspberry-pi/update-from-github.sh | sudo bash" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  echo "This updater requires curl and python3." >&2
  exit 1
fi

ASSET_URL="$(curl --fail --silent --show-error "$API_URL" | python3 -c '
import json
import re
import sys

release = json.load(sys.stdin)
assets = [
    asset["browser_download_url"]
    for asset in release.get("assets", [])
    if re.fullmatch(r"rom-translator-update-v\d+\.\d+\.tar\.gz", asset.get("name", ""))
]
if not assets:
    raise SystemExit("Latest GitHub release has no Raspberry Pi update archive.")
print(assets[0])
')"

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
ARCHIVE="$TEMP_DIR/update.tar.gz"

echo "Downloading latest ROM Translator release..."
curl --fail --location --silent --show-error --retry 3 "$ASSET_URL" --output "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$TEMP_DIR"

SOURCE_ROOT="$TEMP_DIR/rom-translator"
if [[ ! -f "$SOURCE_ROOT/deploy/raspberry-pi/install.sh" ]]; then
  echo "The downloaded release does not contain the Raspberry Pi installer." >&2
  exit 1
fi

bash "$SOURCE_ROOT/deploy/raspberry-pi/install.sh"

if [[ -f /etc/systemd/system/rom-translator-ngrok.service ]] && \
  systemctl is-enabled --quiet rom-translator-ngrok.service; then
  systemctl restart rom-translator-ngrok.service
fi

echo "ROM Translator update complete."