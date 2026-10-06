#!/usr/bin/env bash
# Everything CI runs (.github/workflows/check.yml). One command before you push.
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-./.venv/bin/python}

echo "→ ruff check";      $PY -m ruff check .
echo "→ ruff format";     $PY -m ruff format --check .
echo "→ mypy";            $PY -m mypy
echo "→ line budget";     $PY scripts/check_lines.py --quiet
# The Dockerfile and the workflows are code too, and no secret may ever be committed.
# CI installs these at pinned versions; locally they run when installed
# (brew install hadolint actionlint gitleaks).
for tool in hadolint actionlint gitleaks; do
  if ! command -v "$tool" >/dev/null; then echo "→ $tool: not installed, skipped (CI runs it)"; continue; fi
  echo "→ $tool"
  case "$tool" in
    hadolint) hadolint Dockerfile ;;
    actionlint) actionlint ;;
    gitleaks) gitleaks git --redact --no-banner --log-level warn ;;  # the whole history
  esac
done
# Every locked dependency, dev tools included, against the known vulnerabilities.
echo "→ pip-audit"
locked=$(mktemp)
uv export --frozen --all-groups --no-emit-project --quiet --output-file "$locked"
$PY -m pip_audit --requirement "$locked" --disable-pip --progress-spinner off
rm -f "$locked"
echo "→ tests";           $PY -m pytest --cov
echo "→ web tests";       node tests/test_web.mjs
echo "✓ all green"
