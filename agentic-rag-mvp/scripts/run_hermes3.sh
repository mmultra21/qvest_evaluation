#!/usr/bin/env bash
set -euo pipefail

#!/usr/bin/env bash
set -euo pipefail

# Auto-detect llama.cpp server binary and provide a readiness probe.

# Base llama.cpp directory (can override):
LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp}"

# Common binary locations relative to LLAMA_DIR
POSSIBLE_BINARIES=("$LLAMA_DIR/server" "$LLAMA_DIR/build/server" "$LLAMA_DIR/build/bin/llama-server" "$LLAMA_DIR/build/bin/server")

# Resolve server binary
SERVER_BIN=""
for p in "${POSSIBLE_BINARIES[@]}"; do
  if [ -x "$p" ]; then
    SERVER_BIN="$p"
    break
  fi
done

if [ -z "$SERVER_BIN" ]; then
  echo "Could not find llama.cpp server binary in one of: ${POSSIBLE_BINARIES[*]}"
  echo "Build llama.cpp first or set LLAMA_DIR to the folder containing the server binary."
  exit 1
fi

# Path to your Hermes3 quantized GGUF (override with HERMES3_GGUF)
MODEL_PATH="${HERMES3_GGUF:-$HOME/models/llama/hermes3-8b.Q4_K_M.gguf}"

# Port and host (default to localhost for safety)
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-11434}"

echo "Starting Hermes-3 server: $SERVER_BIN"
echo "Model: $MODEL_PATH" "Host: $HOST Port: $PORT"

# Start server in background
"$SERVER_BIN" \
  -m "$MODEL_PATH" \
  --host "$HOST" \
  --port "$PORT" \
  -c 4096 --keep -1 --mlock &

SERVER_PID=$!

echo "Waiting for server to become ready (timeout 60s)..."
RETRY=0
MAX_RETRIES=60
until curl -sS "http://$HOST:$PORT/health" >/dev/null 2>&1 || [ $RETRY -ge $MAX_RETRIES ]; do
  RETRY=$((RETRY + 1))
  sleep 1
done

if [ $RETRY -ge $MAX_RETRIES ]; then
  echo "Server did not become ready in time. Check logs or run the server manually. (PID=$SERVER_PID)"
  exit 1
fi

echo "Server ready (PID=$SERVER_PID)"
echo "To stop: kill $SERVER_PID"

wait $SERVER_PID