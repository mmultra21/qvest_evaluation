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

UVICORN_CMD=("$PYTHON" -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info)
GRADIO_CMD=("$PYTHON" "$ROOT_DIR/app/main.py")

echo "Starting backend: ${UVICORN_CMD[*]}"
"${UVICORN_CMD[@]}" &
UVICORN_PID=$!
echo "uvicorn PID=$UVICORN_PID"

sleep 0.4

echo "Starting Gradio UI: ${GRADIO_CMD[*]}"
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
