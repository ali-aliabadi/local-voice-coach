#!/usr/bin/env bash
# Everything CI runs (.github/workflows/check.yml). One command before you push.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-./.venv/bin/python}

echo "→ ruff check";      $PY -m ruff check .
echo "→ ruff format";     $PY -m ruff format --check .
echo "→ line budget";     $PY scripts/check_lines.py --quiet
# One command per file: under `set -e`, a failure inside an `a && b && c` chain does not
# stop the script, and a broken test once printed "all green".
echo "→ tests"
for test in tests/test_coach.py tests/test_history.py tests/test_modes.py tests/test_reports.py; do
  $PY "$test"
done
echo "→ web tests";       node tests/test_web.mjs
echo "✓ all green"
