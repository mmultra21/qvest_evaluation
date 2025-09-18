#!/usr/bin/env bash
set -euo pipefail

# dev_run.sh — start backend (uvicorn) and Gradio UI together for local development
# Usage: ./dev_run.sh

# Compute repository root (two levels up from this script: agentic-rag-mvp/scripts -> agentic-rag-mvp -> repo root)
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd "$ROOT_DIR/.." && pwd)

# Prefer the repository-level virtualenv if present, otherwise use the package-level .venv
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  VENV_DIR="$ROOT_DIR/.venv"
fi

# If venv exists, use its python, otherwise assume python on PATH is correct
if [ -x "$VENV_DIR/bin/python" ]; then
  PYTHON="$VENV_DIR/bin/python"
else
  PYTHON="python3"
fi

export PYTHONPATH="$ROOT_DIR"

find_free_port() {
  local start=$1
  local end=$2
  for ((p=start; p<=end; p++)); do
    if ! lsof -i :$p -sTCP:LISTEN >/dev/null 2>&1; then
      echo $p
      return 0
    fi
  done
  return 1
}

# Choose ports (try defaults then fallback range)
UVICORN_PORT=$(find_free_port 8000 8010 || true)
if [ -z "$UVICORN_PORT" ]; then
  echo "No free port found for uvicorn in range 8000-8010" >&2
  exit 1
fi

GRADIO_PORT=$(find_free_port 7860 7870 || true)
if [ -z "$GRADIO_PORT" ]; then
  echo "No free port found for Gradio in range 7860-7870" >&2
  exit 1
fi

UVICORN_CMD=("$PYTHON" -m uvicorn api.main:app --host 127.0.0.1 --port $UVICORN_PORT --log-level info)
export GRADIO_SERVER_PORT=$GRADIO_PORT
GRADIO_CMD=("$PYTHON" "$ROOT_DIR/app/main.py")

echo "Starting backend on port $UVICORN_PORT: ${UVICORN_CMD[*]}"
"${UVICORN_CMD[@]}" &
UVICORN_PID=$!
echo "uvicorn PID=$UVICORN_PID"

sleep 0.4

echo "Starting Gradio UI on port $GRADIO_PORT: ${GRADIO_CMD[*]}"
"${GRADIO_CMD[@]}" &
GRADIO_PID=$!
echo "gradio PID=$GRADIO_PID"

cleanup() {
  echo "Stopping processes..."
  kill "$GRADIO_PID" "$UVICORN_PID" 2>/dev/null || true
  wait "$GRADIO_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  echo "Stopped"
}

trap cleanup EXIT INT TERM

echo "Backend: http://127.0.0.1:8000  |  Gradio: http://127.0.0.1:7860"
echo "Press Ctrl-C to stop"

wait
