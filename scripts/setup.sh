#!/usr/bin/env bash
# One-time setup: Python virtualenv + backend deps + frontend deps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

if [[ ! -d .venv ]]; then
  echo "→ creating virtualenv"
  if ! "$PYTHON" -m venv .venv 2>/dev/null; then
    # Some distro builds ship venv without ensurepip; bootstrap pip manually.
    "$PYTHON" -m venv --without-pip .venv
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    .venv/bin/python /tmp/get-pip.py --quiet
  fi
fi

echo "→ installing backend dependencies"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r backend/requirements.txt

echo "→ installing frontend dependencies"
(cd frontend && npm install)

echo
echo "Setup complete. Start everything with: ./scripts/dev.sh"
