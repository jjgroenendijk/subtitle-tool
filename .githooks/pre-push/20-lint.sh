#!/usr/bin/env bash
# Strict lint and format check over the whole tree, applying no fixes: ruff for
# Python, mdformat + pymarkdown for Markdown. Ruff rules and line length live in
# pyproject.toml; mdformat reads .mdformat.toml and pymarkdown reads
# [tool.pymarkdown], so the hook and CI stay in sync.
set -euo pipefail

# Run a dev tool, preferring the project's uv environment over one on PATH.
run() { if command -v uv >/dev/null 2>&1; then uv run "$@"; else "$@"; fi; }
# Fail with an actionable message when a needed tool is missing. uv provides all
# of them via `uv sync --extra dev`, so its presence is enough.
require() {
  command -v uv >/dev/null 2>&1 && return 0
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "[ERROR] $1 not found. Install dev dependencies: uv sync --extra dev" >&2
  exit 1
}

require ruff
require mdformat
require pymarkdown

echo "[INFO] Running strict ruff and Markdown lint and format check..."
fail=0
run ruff check || fail=1
run ruff format --check || fail=1
all_md="$(git ls-files '*.md')"
if [ -n "$all_md" ]; then
  # shellcheck disable=SC2086 # word-splitting the tracked .md list is intended.
  run mdformat --check $all_md || fail=1
  # shellcheck disable=SC2086
  run pymarkdown scan $all_md || fail=1
fi
if [ "$fail" -ne 0 ]; then
  echo "[ERROR] Lint/format check failed. Run 'uv run ruff check --fix', 'uv run ruff format', and 'uv run mdformat <files>'." >&2
  exit 1
fi
echo "[OK] Lint and format passed."
