#!/usr/bin/env bash
# Run the backend test suite. Pass --slow to include the 10k-row and timing tests.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [[ "${1:-}" == "--slow" ]]; then
  exec ../.venv/bin/python -m pytest -q
fi
exec ../.venv/bin/python -m pytest -q -m "not slow"
