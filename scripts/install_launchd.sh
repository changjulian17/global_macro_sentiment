#!/bin/zsh
set -euo pipefail

LABEL="com.globalmacro.sentiment.daily"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
RUN_SCRIPT="$PROJECT_DIR/scripts/run_batch.sh"

mkdir -p "$PLIST_DIR"
mkdir -p "$PROJECT_DIR/logs"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$RUN_SCRIPT</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>20</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/logs/launchd.stdout.log</string>

  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/logs/launchd.stderr.log</string>
</dict>
</plist>
EOF

chmod +x "$RUN_SCRIPT"

# Unload if already loaded, then load fresh.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed launchd job: $LABEL"
echo "Plist: $PLIST_PATH"
echo "Runs at login plus daily at 20:00 while your Mac is on and you are logged in."
echo "Logs: $PROJECT_DIR/logs/scheduler.log"
