#!/usr/bin/env bash
# Everything CI runs (.github/workflows/check.yml). One command before you push.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-./.venv/bin/python}

echo "→ ruff check";      $PY -m ruff check .
echo "→ ruff format";     $PY -m ruff format --check .
echo "→ mypy";            $PY -m mypy
echo "→ line budget";     $PY scripts/check_lines.py --quiet
# The Dockerfile and the workflows are code too. CI installs both linters at pinned
# versions; locally they run when installed (brew install hadolint actionlint).
for tool in hadolint actionlint; do
  if ! command -v "$tool" >/dev/null; then echo "→ $tool: not installed, skipped (CI runs it)"; continue; fi
  echo "→ $tool"
  if [ "$tool" = hadolint ]; then hadolint Dockerfile; else actionlint; fi
done
echo "→ tests";           $PY -m pytest --cov
echo "→ web tests";       node tests/test_web.mjs
echo "✓ all green"
