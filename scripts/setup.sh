#!/usr/bin/env bash
# One-time setup: Python virtualenv + backend deps + frontend deps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

if [[ ! -d .venv ]]; then
  echo "→ creating virtualenv"
  if ! "$PYTHON" -m venv .venv >/dev/null 2>&1; then
    # Some distro builds ship venv without ensurepip (Debian/Ubuntu split it into
    # python3-venv). Fall back to a pip-less venv and bootstrap pip into it.
    echo "  ensurepip unavailable — bootstrapping pip manually"
    rm -rf .venv
    "$PYTHON" -m venv --without-pip .venv
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    .venv/bin/python /tmp/get-pip.py --quiet
  fi
fi

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo "Could not provision a working virtualenv with pip." >&2
  echo "On Debian/Ubuntu: sudo apt install python3-venv" >&2
  exit 1
fi

echo "→ installing backend dependencies"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r backend/requirements.txt

echo "→ installing frontend dependencies"
(cd frontend && npm install)

.venv/bin/python -c "import fastapi, sqlalchemy, pydantic" || {
  echo "Backend dependencies did not import cleanly." >&2
  exit 1
}

echo
echo "Setup complete. Start everything with: ./scripts/dev.sh"
