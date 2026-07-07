#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.proxy.pid"
LOCK_FILE="$PROJECT_DIR/.proxy.lock"
LOG_FILE="$PROJECT_DIR/proxy.log"

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "Another start is already in progress."; exit 1; }

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Proxy already running (PID $(cat "$PID_FILE")). Use scripts/stop.sh first."
    exit 1
fi

cd "$PROJECT_DIR"

# Pass through any env overrides (e.g., LOG_LEVEL=DEBUG ./scripts/start.sh)
uv run start_proxy.py >> "$LOG_FILE" 2>&1 &
PROXY_PID=$!
echo "$PROXY_PID" > "$PID_FILE"

sleep 2

if kill -0 "$PROXY_PID" 2>/dev/null; then
    PORT=$(grep -oP 'PORT=\K[0-9]+' "$PROJECT_DIR/.env" 2>/dev/null || echo "3000")
    echo "Proxy started (PID $PROXY_PID)"
    echo "  Log: $LOG_FILE"
    echo "  Health: http://127.0.0.1:${PORT}/health"
else
    echo "Proxy failed to start. Check $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
