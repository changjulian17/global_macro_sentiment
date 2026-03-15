#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$LOG_DIR"

echo "[$STAMP] Starting scheduled run" >> "$LOG_DIR/scheduler.log"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[$STAMP] ERROR: Python venv not found at $VENV_PYTHON" >> "$LOG_DIR/scheduler.log"
  exit 1
fi

cd "$PROJECT_DIR"

# --no-browser is essential for background launchd runs.
"$VENV_PYTHON" run.py --no-browser >> "$LOG_DIR/scheduler.log" 2>&1

END_STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$END_STAMP] Finished scheduled run" >> "$LOG_DIR/scheduler.log"
