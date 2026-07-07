#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.proxy.pid"

rm -f "$PROJECT_DIR/.proxy.lock"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Checking for stray processes..."
    if pgrep -af "$PROJECT_DIR.*start_proxy" > /dev/null 2>&1; then
        pkill -f "$PROJECT_DIR.*start_proxy"
        echo "Killed stray proxy process."
    else
        echo "No proxy running."
    fi
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    for i in 1 2 3 4 5; do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID" 2>/dev/null
    fi
    echo "Proxy stopped (PID $PID)."
else
    echo "PID $PID not running (stale PID file)."
fi

rm -f "$PID_FILE"
rm -f "$PROJECT_DIR/.proxy.lock"
