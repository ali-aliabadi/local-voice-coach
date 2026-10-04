#!/usr/bin/env bash
# Everything CI runs (.github/workflows/check.yml). One command before you push.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-./.venv/bin/python}

echo "→ ruff check";      $PY -m ruff check .
echo "→ ruff format";     $PY -m ruff format --check .
echo "→ line budget";     $PY scripts/check_lines.py --quiet
echo "→ tests";           $PY tests/test_coach.py && $PY tests/test_history.py \
                          && $PY tests/test_reports.py \
                          && $PY tests/test_modes.py
echo "→ web tests";       node tests/test_web.mjs
echo "✓ all green"
