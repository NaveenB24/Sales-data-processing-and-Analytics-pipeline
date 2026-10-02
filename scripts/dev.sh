#!/usr/bin/env bash
# Start the API and the Vite dev server together. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x .venv/bin/python ]]; then
  echo "No virtualenv found. Run scripts/setup.sh first." >&2
  exit 1
fi

cleanup() { jobs -p | xargs -r kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "→ API      http://127.0.0.1:8000  (docs at /api/docs)"
(cd backend && exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &

if [[ ! -d frontend/node_modules ]]; then
  echo "→ installing frontend dependencies"
  (cd frontend && npm install --silent)
fi

echo "→ Frontend http://127.0.0.1:5173"
(cd frontend && exec npm run dev -- --host 127.0.0.1 --port 5173) &

wait
