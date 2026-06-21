#!/usr/bin/env bash
# Run the test suite when the commit touches Python; skip otherwise. Source paths
# come from pyproject.toml; PYTEST_ARGS appends extra pytest arguments.
set -euo pipefail

run() { if command -v uv >/dev/null 2>&1; then uv run "$@"; else "$@"; fi; }

has_py=0
while IFS= read -r f; do
  case "$f" in
    *.py) has_py=1; break ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

if [ "$has_py" -eq 0 ]; then
  echo "[OK] Tests: no staged Python files, skipping suite."
  exit 0
fi

if ! command -v uv >/dev/null 2>&1 && ! command -v pytest >/dev/null 2>&1; then
  echo "[ERROR] pytest not found. Install dev dependencies: uv sync --extra dev" >&2
  exit 1
fi

echo "[INFO] Running test suite..."
# shellcheck disable=SC2086 # PYTEST_ARGS is intentionally word-split.
if ! run pytest ${PYTEST_ARGS:-}; then
  echo "[ERROR] Tests failed. Fix them before committing (bypass: --no-verify)." >&2
  exit 1
fi
echo "[OK] Tests passed."
