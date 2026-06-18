#!/usr/bin/env bash
# Format and auto-fix staged Python (ruff) and Markdown (mdformat), re-stage the
# result so the commit matches what is checked, then fail on anything the fixers
# cannot resolve (pymarkdown gates the issues mdformat cannot auto-fix). Ruff
# rules and line length live in pyproject.toml; mdformat reads .mdformat.toml and
# pymarkdown reads [tool.pymarkdown], so the hook and CI stay in sync.
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

py=(); md=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *.py) py+=("$f") ;;
    *.md) md+=("$f") ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

fail=0
if [ ${#py[@]} -gt 0 ]; then
  require ruff
  echo "[INFO] Formatting and auto-fixing ${#py[@]} staged Python file(s)..."
  run ruff format "${py[@]}"
  run ruff check --fix "${py[@]}" || true
  git add -- "${py[@]}"
  run ruff check "${py[@]}" || fail=1
  run ruff format --check "${py[@]}" || fail=1
fi

if [ ${#md[@]} -gt 0 ]; then
  require mdformat
  require pymarkdown
  echo "[INFO] Formatting ${#md[@]} staged Markdown file(s)..."
  run mdformat "${md[@]}"
  git add -- "${md[@]}"
  run mdformat --check "${md[@]}" || fail=1
  run pymarkdown scan "${md[@]}" || fail=1
fi

if [ ${#py[@]} -eq 0 ] && [ ${#md[@]} -eq 0 ]; then
  echo "[OK] Lint: no staged Python or Markdown files to check."
  exit 0
fi
if [ "$fail" -ne 0 ]; then
  echo "[ERROR] Lint check failed (unfixable issues above). Resolve them and re-commit." >&2
  exit 1
fi
echo "[OK] Lint and format passed."
