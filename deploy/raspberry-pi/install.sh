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

NGROK_USER="${SUDO_USER:-pi}"
NGROK_SERVICE_READY=0
if [[ "$NGROK_USER" != "root" ]] && getent passwd "$NGROK_USER" >/dev/null 2>&1; then
  NGROK_HOME="$(getent passwd "$NGROK_USER" | cut -d: -f6)"
  NGROK_BIN="$(runuser -u "$NGROK_USER" -- env PATH="$NGROK_HOME/.local/bin:$NGROK_HOME/bin:/usr/local/bin:/usr/bin:/bin" sh -c 'command -v ngrok' 2>/dev/null || true)"
  if [[ -n "$NGROK_BIN" ]] && runuser -u "$NGROK_USER" -- env HOME="$NGROK_HOME" "$NGROK_BIN" config check >/dev/null 2>&1; then
    NGROK_SERVICE_READY=1
  else
    echo "ngrok is not installed or configured for $NGROK_USER; app update will continue without enabling its tunnel service."
  fi
else
  echo "Could not identify the non-root Pi user for ngrok; app update will continue without enabling its tunnel service."
fi

if ss -H -ltn 'sport = :8081' | grep -q .; then
  if ! systemctl is-active --quiet rom-translator.service || \
    ! grep -Eq '^[[:space:]]*listen[[:space:]]+8081;' /etc/nginx/conf.d/rom-translator.conf 2>/dev/null; then
    echo "Port 8081 is already in use by another service; no files were installed." >&2
    exit 1
  fi
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
if [[ "$NGROK_SERVICE_READY" -eq 1 ]]; then
  sed \
    -e "s|@NGROK_USER@|$NGROK_USER|g" \
    -e "s|@NGROK_HOME@|$NGROK_HOME|g" \
    -e "s|@NGROK_BIN@|$NGROK_BIN|g" \
    "$SOURCE_ROOT/deploy/raspberry-pi/rom-translator-ngrok.service" \
    > /etc/systemd/system/rom-translator-ngrok.service
  chmod 0644 /etc/systemd/system/rom-translator-ngrok.service
fi

nginx -t
systemctl daemon-reload
systemctl enable rom-translator.service
systemctl restart rom-translator.service
systemctl reload nginx
if [[ "$NGROK_SERVICE_READY" -eq 1 ]]; then
  systemctl enable rom-translator-ngrok.service
  if systemctl is-active --quiet rom-translator-ngrok.service; then
    systemctl restart rom-translator-ngrok.service
  fi
fi

curl --fail --silent --show-error --retry 10 --retry-connrefused \
  http://127.0.0.1:8081/api/
printf '\nApplication is available at http://%s:8081/\n' "$(hostname -I | awk '{print $1}')"
if [[ "$NGROK_SERVICE_READY" -eq 1 ]]; then
  printf 'ngrok tunnel service is enabled and will start on boot.\n'
  printf 'To start it now, stop any manually running ngrok process, then run: sudo systemctl start rom-translator-ngrok\n'
fi