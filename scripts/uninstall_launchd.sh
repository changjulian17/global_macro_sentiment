#!/bin/zsh
set -euo pipefail

LABEL="com.globalmacro.sentiment.daily"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST_PATH"

echo "Removed launchd job: $LABEL"
