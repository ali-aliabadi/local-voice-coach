#!/usr/bin/env bash
# Everything CI would run. One command before you push.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-./.venv/bin/python}

echo "→ ruff check";      ruff check .
echo "→ ruff format";     ruff format --check .
echo "→ line budget";     $PY scripts/check_lines.py --quiet
echo "→ tests";           $PY tests/test_coach.py && $PY tests/test_history.py
echo "✓ all green"
