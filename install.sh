#!/bin/bash
# Guided install check. Safe to re-run. It never installs system software and never touches
# anything outside this folder, except the optional LinkedIn skill, and only if you say yes.
set -euo pipefail
cd "$(dirname "$0")"
say() { printf '\n%s\n' "$*"; }
ask() { local a; read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]; }

say "Job Search Dashboard: install check"
command -v python3 >/dev/null || { echo "Python 3 is missing. Install Python 3.10 or newer from https://www.python.org/downloads/ and run this again."; exit 1; }
mkdir -p data
python3 scripts/setup.py --doctor || true

say "Running the self-tests (about 15 seconds, no network, no cost)..."
if python3 -m unittest discover -s tests >/dev/null 2>&1; then echo "  tests passed"; else echo "  tests FAILED: run 'python3 -m unittest discover -s tests' to see why, and open an issue with the output."; fi

if [ -d optional-skills/linkedin-easy-apply ]; then
  say "Optional: LinkedIn Easy Apply skill"
  echo "  It finds and fills LinkedIn Easy Apply forms in your own Chrome and stops for your approval before every submit."
  echo "  RISK: automating LinkedIn may conflict with LinkedIn's User Agreement. You use it at your own risk."
  echo "  It needs Claude Code's 'Claude in Chrome' extension and you logged in to LinkedIn."
  if ask "Install it to ~/.claude/skills/linkedin-easy-apply ?"; then
    dest="$HOME/.claude/skills/linkedin-easy-apply"
    if [ -e "$dest" ]; then
      echo "  $dest already exists, so I will not touch it. Move or delete it first if you want a fresh copy."
    else
      mkdir -p "$HOME/.claude/skills" && cp -R optional-skills/linkedin-easy-apply "$dest"
      echo "  Installed. The setup interview will configure it."
    fi
  else
    echo "  Skipped. You can add it later by asking Claude to 'install the LinkedIn skill'."
  fi
fi

say "Next: configure it."
echo "  1. Open Claude Code in THIS folder:   claude"
echo "  2. Type:                              /job-search-setup"
echo "  Claude interviews you, writes your config, and runs your first search."
