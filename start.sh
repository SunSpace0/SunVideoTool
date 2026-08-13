#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-$PWD/.venv/bin/python}"
HOST="${HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-}"

if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "创建 Python 虚拟环境..."
  python3 -m venv .venv
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -e ".[separation]"
fi

read_port() {
  "$PYTHON_BIN" - "$1" <<'PY'
from sunvideotool.config import load_config
import sys
key = sys.argv[1]
default = 18881 if key == "frontend_port" else 18880
print(load_config().get('runtime', {}).get(key, default))
PY
}

BACKEND_PORT="$(read_port port)"
if [ -z "$FRONTEND_PORT" ]; then
  FRONTEND_PORT="$(read_port frontend_port)"
fi

if [ ! -d frontend/node_modules ]; then
  echo "安装前端依赖..."
  npm --prefix frontend install
fi

cleanup() {
  trap - EXIT INT TERM
  if [ -n "${FRONTEND_PID:-}" ]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  if [ -n "${BACKEND_PID:-}" ]; then kill "$BACKEND_PID" 2>/dev/null || true; pkill -P "$BACKEND_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

echo "后端: http://$HOST:$BACKEND_PORT"
echo "前端: http://$HOST:$FRONTEND_PORT"

"$PYTHON_BIN" -m uvicorn sunvideotool.api:app \
  --host "$HOST" \
  --port "$BACKEND_PORT" \
  --reload &
BACKEND_PID=$!

VITE_PORT="$FRONTEND_PORT" \
VITE_BACKEND_HOST="$HOST" \
VITE_BACKEND_PORT="$BACKEND_PORT" \
npm --prefix frontend run dev \
  -- --host "$HOST" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

wait
