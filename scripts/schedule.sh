#!/bin/bash
# Install (or remove) a macOS launchd job that runs one job-search cycle every morning.
#   scripts/schedule.sh install [HH:MM]   default 07:30, runs run_cycle.py --notify
#   scripts/schedule.sh remove
#   scripts/schedule.sh test      run the installed job now under launchd and show the result
#   scripts/schedule.sh status
# Nothing is installed until you run `install` yourself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.jobsearch.cycle"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
case "${1:-status}" in
  install)
    # macOS blocks launchd jobs from reading ~/Desktop, ~/Documents, ~/Downloads and iCloud Drive (privacy/TCC rules).
    # The job then dies instantly with exit 78 and no log. Refuse rather than install something that cannot work.
    case "$ROOT" in
      "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
        echo "ERROR: $ROOT is in a macOS-protected folder; a scheduled job cannot read it."
        echo "Move the project somewhere unprotected (for example: mv \"$ROOT\" \"$HOME/job-search-skill\"), then run install again."
        exit 2 ;;
    esac
    T="${2:-07:30}"; H="${T%%:*}"; M="${T##*:}"
    CLAUDE_DIR="$(dirname "$(command -v claude || echo /usr/local/bin/claude)")"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$(command -v python3)</string><string>$ROOT/scripts/run_cycle.py</string><string>--notify</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$CLAUDE_DIR:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$((10#$H))</integer><key>Minute</key><integer>$((10#$M))</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/data/cycle.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/cycle.log</string>
</dict></plist>
EOF
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST"
    echo "Installed: runs daily at $T. Log: $ROOT/data/cycle.log. Remove with: $0 remove" ;;
  remove)
    launchctl unload "$PLIST" 2>/dev/null || true; rm -f "$PLIST"; echo "Removed." ;;
  test)
    # Run the installed job NOW under launchd's real environment (this is what proves keychain/auth access works unattended).
    launchctl list | grep -q "$LABEL" || { echo "Not installed. Run: $0 install"; exit 1; }
    : > "$ROOT/data/cycle.log"
    launchctl kickstart -k "gui/$(id -u)/$LABEL"
    echo "Started. Waiting up to 5 minutes for data/last-report.md ..."
    for _ in $(seq 60); do sleep 5; pgrep -f "scripts/run_cycle.py" >/dev/null || break; done
    echo "--- cycle.log"; tail -20 "$ROOT/data/cycle.log"; echo "--- last report"; cat "$ROOT/data/last-report.md" 2>/dev/null
    code="$(launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | awk '/last exit code/{print $5}' | tr -d ':')"
    [ "$code" = "78" ] && echo "EXIT 78: launchd could not start the job. Usual cause: the project is in ~/Desktop, ~/Documents or ~/Downloads (macOS blocks it)." || true ;;
  status)
    launchctl list | grep "$LABEL" || echo "Not installed."
    [ -f "$ROOT/data/last-report.md" ] && { echo "--- last report"; cat "$ROOT/data/last-report.md"; } || true ;;
esac
