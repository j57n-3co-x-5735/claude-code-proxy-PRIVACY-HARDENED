#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/proxy.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "No log file at $LOG_FILE"
    exit 1
fi

tail -f "$LOG_FILE"
