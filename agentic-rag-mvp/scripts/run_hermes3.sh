#!/usr/bin/env bash
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp}"
# Support both old and new binary names
POSSIBLE_BINARIES=(
  "$LLAMA_DIR/build/bin/llama-server"
  "$LLAMA_DIR/build/bin/server"
  "$LLAMA_DIR/server"
  "$LLAMA_DIR/build/server"
)

SERVER_BIN=""
for p in "${POSSIBLE_BINARIES[@]}"; do
  if [[ -x "$p" ]]; then SERVER_BIN="$p"; break; fi
done
if [[ -z "$SERVER_BIN" ]]; then
  echo "❌ Could not find llama-server binary under $LLAMA_DIR" >&2
  exit 1
fi

MODEL_PATH="${HERMES3_GGUF:-$HOME/models/llama/hermes3-8b.Q4_K_M.gguf}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-11434}"
LOG="${LOG:-/tmp/llm_server.log}"
PID_FILE="${PID_FILE:-/tmp/llm_server.pid}"

echo "Starting Hermes-3 server: $SERVER_BIN"
echo "Model: $MODEL_PATH  Host: $HOST  Port: $PORT"
echo "(logs: $LOG)"

# Start in background & log to file
"$SERVER_BIN" \
  -m "$MODEL_PATH" \
  --host "$HOST" --port "$PORT" \
  -c 4096 --keep -1 --mlock \
  >"$LOG" 2>&1 &

SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# Readiness: wait for HTTP 200 on /health
echo -n "Waiting for server to become ready (timeout 180s)"
READY=0
for i in {1..180}; do
  # capture only HTTP code
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://$HOST:$PORT/health" || true)
  if [[ "$CODE" == "200" ]]; then
    READY=1
    break
  fi
  echo -n "."
  sleep 1
done
echo

if [[ "$READY" -ne 1 ]]; then
  echo "❌ Server did not become ready in time. Last 50 log lines:"
  tail -n 50 "$LOG" || true
  kill "$SERVER_PID" 2>/dev/null || true
  exit 1
fi

echo "✅ Server ready (PID=$(cat "$PID_FILE")). To stop: kill $(cat "$PID_FILE")"
# Keep the process in the foreground of the script so Ctrl+C stops both
wait "$SERVER_PID"