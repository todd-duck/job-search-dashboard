#!/bin/bash
# Prints lowercase company names the user has already applied to or prepared for:
# per-company folders in the applications dir, plus rows in data/tracking.csv.
# Usage: already_applied.sh [company]   -> with an arg, exits 0 if seen (prints the match), 1 if not.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APPS_DIR="$(python3 -c "import json,os;print(os.path.expanduser(json.load(open('$SKILL_DIR/config.json'))['profile']['applications_dir']))")"

norm() { tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+//g'; }

list() {
  # Folder names like "acme-resume", "acme-Principal", "acme-resume-partner_solution_architect" -> the company part.
  # Folders listed in profile.ignore_folders (config.json) are not companies and are skipped.
  IGNORE="$(python3 -c "import json;print('|'.join(json.load(open('$SKILL_DIR/config.json'))['profile'].get('ignore_folders', [])) or '^$')")"
  { find "$APPS_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '.*' -exec basename {} \; 2>/dev/null || true; } \
    | { grep -viE "^($IGNORE)$" || true; } \
    | sed -E 's/[-_].*$//' | norm
  # tracking.csv: Company (col 2) for rows with Status (col 9) = Submitted
  { tail -n +2 "$SKILL_DIR/data/tracking.csv" 2>/dev/null || true; } | python3 -c "import csv,sys; [print(r[1]) for r in csv.reader(sys.stdin) if len(r)>8 and r[8]=='Submitted']" | norm
}

if [ $# -gt 0 ]; then
  q="$(echo "$*" | norm)"
  list | sort -u | awk -v q="$q" 'length($0)>=3 && (index(q,$0)==1 || index($0,q)==1) {print; found=1} END {exit !found}'
else
  list | sort -u
fi
