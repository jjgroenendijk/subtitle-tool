#!/usr/bin/env bash
# Run the full test suite with the application-code coverage gate. The source
# paths and the fail_under threshold come from pyproject.toml's [tool.coverage]
# tables, so the hook, CI, and a manual `uv run pytest --cov` all share one
# threshold. PYTEST_ARGS appends extra pytest arguments.
set -euo pipefail

run() { if command -v uv >/dev/null 2>&1; then uv run "$@"; else "$@"; fi; }

if ! command -v uv >/dev/null 2>&1 && ! command -v pytest >/dev/null 2>&1; then
  echo "[ERROR] pytest not found. Install dev dependencies: uv sync --extra dev" >&2
  exit 1
fi

echo "[INFO] Running test suite with coverage gate..."
# shellcheck disable=SC2086 # PYTEST_ARGS is intentionally word-split.
if ! run pytest --cov ${PYTEST_ARGS:-}; then
  echo "[ERROR] Tests failed or coverage below the threshold in pyproject.toml. Fix before pushing (bypass: --no-verify)." >&2
  exit 1
fi
echo "[OK] Tests passed."
