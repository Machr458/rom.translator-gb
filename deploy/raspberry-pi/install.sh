#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run this installer with sudo: sudo bash deploy/raspberry-pi/install.sh" >&2
  exit 1
fi

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_ROOT=/opt/rom-translator
DATA_ROOT=/var/lib/rom-translator

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Expected a 64-bit ARM system (aarch64), got: $(uname -m)" >&2
  exit 1
fi

if [[ ! -f "$SOURCE_ROOT/backend/server.py" || ! -f "$SOURCE_ROOT/backend/requirements-pi.txt" ]]; then
  echo "Run this script from a complete project checkout." >&2
  exit 1
fi

if [[ ! -f "$SOURCE_ROOT/frontend/build/index.html" ]]; then
  echo "Frontend build is missing. Build it on the development computer first: yarn --cwd frontend build" >&2
  exit 1
fi

if ss -H -ltn 'sport = :8081' | grep -q .; then
  echo "Port 8081 is already in use; no files were installed." >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx python3-venv python3-pip rsync curl

if ! id romtrans >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_ROOT" --shell /usr/sbin/nologin romtrans
fi

install -d -m 0755 "$APP_ROOT/backend" "$APP_ROOT/frontend/build"
install -d -o romtrans -g romtrans -m 0750 "$DATA_ROOT"

rsync -a \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='rom_sessions/' \
  --exclude='tests/' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='requirements.txt' \
  "$SOURCE_ROOT/backend/" "$APP_ROOT/backend/"
rsync -a "$SOURCE_ROOT/frontend/build/" "$APP_ROOT/frontend/build/"

if [[ ! -x "$APP_ROOT/venv/bin/python" ]]; then
  python3 -m venv "$APP_ROOT/venv"
fi
"$APP_ROOT/venv/bin/python" -m pip install --prefer-binary -r "$APP_ROOT/backend/requirements-pi.txt"

install -m 0644 "$SOURCE_ROOT/deploy/raspberry-pi/rom-translator.service" \
  /etc/systemd/system/rom-translator.service
install -m 0644 "$SOURCE_ROOT/deploy/raspberry-pi/rom-translator.nginx.conf" \
  /etc/nginx/conf.d/rom-translator.conf

nginx -t
systemctl daemon-reload
systemctl enable rom-translator.service
systemctl restart rom-translator.service
systemctl reload nginx

curl --fail --silent --show-error --retry 10 --retry-connrefused \
  http://127.0.0.1:8081/api/
printf '\nApplication is available at http://%s:8081/\n' "$(hostname -I | awk '{print $1}')"