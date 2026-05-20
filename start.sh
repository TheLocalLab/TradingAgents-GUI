#!/usr/bin/env bash
# ============================================================
# TradingAgents — start script (macOS / Linux)
#
# Just launches the GUI. If install.sh hasn't been run yet
# (no .venv), prints a clear error and exits — does NOT auto-install.
#
# Pass any extra args and they're forwarded to the GUI:
#   ./start.sh --host 0.0.0.0 --port 5555
# ============================================================

set -euo pipefail
cd "$(dirname "$0")"

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# ---- 1. Check install has been run ----------------------------------------
if [[ ! -x ".venv/bin/python" ]]; then
  cat <<EOF

  [X] No virtual environment found at .venv/

      Run ./install.sh first to set up dependencies.
      You only need to install once.

EOF
  exit 1
fi

if [[ ! -f ".venv/.deps-installed.txt" ]]; then
  cat <<EOF

  [!] Install marker missing - dependencies may not be set up.
      Run ./install.sh to (re)install.

EOF
  exit 1
fi

# Warn (but don't fail) if pyproject.toml changed since install.
if command -v sha1sum >/dev/null 2>&1; then
  CURR_HASH="$(sha1sum pyproject.toml | awk '{print $1}')"
else
  CURR_HASH="$(shasum pyproject.toml | awk '{print $1}')"
fi
OLD_HASH="$(cat .venv/.deps-installed.txt)"
if [[ "$CURR_HASH" != "$OLD_HASH" ]]; then
  echo
  echo "  [!] pyproject.toml has changed since install."
  echo "      Consider re-running ./install.sh to pick up new dependencies."
  echo "      Continuing anyway in 3 seconds..."
  sleep 3
fi

# ---- 2. Launch ------------------------------------------------------------
echo
echo "  [+] Starting TradingAgents GUI..."
echo "      Open in your browser:  http://127.0.0.1:5000"
echo "      Press Ctrl-C to stop."
echo

exec .venv/bin/python -m gui.app "$@"
