#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
PUBLISH_AND_PUSH="${PUBLISH_AND_PUSH:-true}"
TRY_FINTWIT="${TRY_FINTWIT:-true}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"

mkdir -p "$LOG_DIR"

echo "[$STAMP] Starting scheduled run" >> "$LOG_DIR/scheduler.log"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[$STAMP] ERROR: Python venv not found at $VENV_PYTHON" >> "$LOG_DIR/scheduler.log"
  exit 1
fi

cd "$PROJECT_DIR"

# Keep local scheduler branch aligned before generating a new publish commit.
if [[ "$PUBLISH_AND_PUSH" == "true" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if [[ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Skipping git pull --rebase: worktree not clean" >> "$LOG_DIR/scheduler.log"
    else
      git pull --rebase origin "$DEFAULT_BRANCH" >> "$LOG_DIR/scheduler.log" 2>&1 || true
    fi
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Skipping git pull --rebase: not a git worktree" >> "$LOG_DIR/scheduler.log"
  fi
fi

if [[ "$PUBLISH_AND_PUSH" == "true" ]]; then
  TRY_FINTWIT="$TRY_FINTWIT" bash "$PROJECT_DIR/scripts/publish_pages.sh" >> "$LOG_DIR/scheduler.log" 2>&1

  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git add docs/index.html docs/build-info.txt docs/.nojekyll >> "$LOG_DIR/scheduler.log" 2>&1 || true
    if git diff --cached --quiet; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] No docs changes to commit" >> "$LOG_DIR/scheduler.log"
    else
      COMMIT_MSG="chore: update pages report $(date -u '+%Y-%m-%d %H:%M UTC')"
      git commit -m "$COMMIT_MSG" >> "$LOG_DIR/scheduler.log" 2>&1 || true
      git push origin "$DEFAULT_BRANCH" >> "$LOG_DIR/scheduler.log" 2>&1 || true
    fi
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Skipping commit/push: not a git worktree" >> "$LOG_DIR/scheduler.log"
  fi
else
  # --no-browser is essential for background launchd runs.
  "$VENV_PYTHON" run.py --no-browser >> "$LOG_DIR/scheduler.log" 2>&1
fi

END_STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$END_STAMP] Finished scheduled run" >> "$LOG_DIR/scheduler.log"
