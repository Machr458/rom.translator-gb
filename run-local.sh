#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

for command in python3 node corepack; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/backend/requirements-pi.txt"
corepack yarn --cwd "$ROOT_DIR/frontend" install --frozen-lockfile

(
  cd "$ROOT_DIR/backend"
  exec "$VENV_DIR/bin/python" -m uvicorn server:app --host 127.0.0.1 --port 8001
) &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "ROM Translator is starting at http://localhost:3000"
corepack yarn --cwd "$ROOT_DIR/frontend" start