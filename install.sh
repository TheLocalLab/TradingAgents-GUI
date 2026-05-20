#!/usr/bin/env bash
# ============================================================
# TradingAgents — install script (macOS / Linux)
#
# Sets up the Python environment ONCE. After this finishes,
# use ./start.sh to launch the GUI — no reinstall needed.
#
# Re-run this script any time you pull updates or change deps.
# ============================================================

set -euo pipefail
cd "$(dirname "$0")"

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# ---- 1. Locate Python -----------------------------------------------------
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
if [[ -z "$PY" ]]; then
  cat <<EOF

  [X] Python 3.10+ was not found on your PATH.
      macOS:    brew install python@3.12
      Debian:   sudo apt install python3.12 python3.12-venv
      Fedora:   sudo dnf install python3.12

EOF
  exit 1
fi
echo "  [i] Using $PY ($($PY --version))"

# ---- 2. Create venv -------------------------------------------------------
if [[ -x ".venv/bin/python" ]]; then
  echo "  [i] Existing virtual environment detected at .venv/"
  read -r -p "      Reinstall from scratch? [y/N] " yn
  if [[ "$yn" =~ ^[Yy]$ ]]; then
    echo "  [*] Removing existing .venv ..."
    rm -rf .venv
    "$PY" -m venv .venv
  fi
else
  echo "  [*] Creating virtual environment in .venv ..."
  "$PY" -m venv .venv
fi
VPY=".venv/bin/python"

# ---- 3. Install deps ------------------------------------------------------
echo
echo "  [*] Upgrading pip ..."
"$VPY" -m pip install --upgrade pip --quiet

echo "  [*] Installing TradingAgents and GUI dependencies (this may take a minute) ..."
"$VPY" -m pip install -e ".[gui]"

# ---- 4. Record success ----------------------------------------------------
if command -v sha1sum >/dev/null 2>&1; then
  PYPROJECT_HASH="$(sha1sum pyproject.toml | awk '{print $1}')"
else
  PYPROJECT_HASH="$(shasum pyproject.toml | awk '{print $1}')"
fi
echo "$PYPROJECT_HASH" > ".venv/.deps-installed.txt"

cat <<EOF

  ============================================================
   Install complete. To launch the GUI, run:

       ./start.sh

   Or directly:

       .venv/bin/python -m gui.app
  ============================================================

EOF
