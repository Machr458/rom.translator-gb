#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="Machr458/rom.translator-gb"
API_URL="https://api.github.com/repos/${REPOSITORY}/releases?per_page=100"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run this updater with sudo: curl -fsSL https://raw.githubusercontent.com/${REPOSITORY}/main/deploy/raspberry-pi/update-from-github.sh | sudo bash" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  echo "This updater requires curl and python3." >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
RELEASE_JSON="$TEMP_DIR/release.json"

if ! HTTP_STATUS="$(curl --silent --show-error --retry 3 \
  --output "$RELEASE_JSON" --write-out '%{http_code}' "$API_URL")"; then
  echo "Could not reach the GitHub Releases API. Check the Pi internet connection and try again." >&2
  exit 1
fi

if [[ "$HTTP_STATUS" == "404" ]]; then
  echo "Could not find the GitHub releases list. Check the repository URL and try again." >&2
  exit 1
fi

if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "GitHub Releases API returned HTTP $HTTP_STATUS. Try again later." >&2
  exit 1
fi

ASSET_URL="$(python3 - "$RELEASE_JSON" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as response:
        release = json.load(response)
except (OSError, json.JSONDecodeError):
    raise SystemExit("GitHub returned an invalid release response.")

if not isinstance(release, list):
  raise SystemExit("GitHub returned an invalid release list.")

assets = []
for item in release:
  tag = item.get("tag_name", "")
  version = re.fullmatch(r"v(\d+)\.(\d+)", tag)
  if not version or item.get("draft") or item.get("prerelease"):
    continue

  expected_name = f"rom-translator-update-{tag}.tar.gz"
  for asset in item.get("assets", []):
    if asset.get("name") == expected_name and asset.get("browser_download_url"):
      assets.append(((int(version.group(1)), int(version.group(2))), asset["browser_download_url"]))

if not assets:
  raise SystemExit("No published Raspberry Pi update archive was found in the GitHub releases.")
print(max(assets, key=lambda item: item[0])[1])
PY
)"

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