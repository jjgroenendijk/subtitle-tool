#!/usr/bin/env bash
# Run strict ruff linting and formatting, failing on any unresolved issue.
#
# Usage:
#   check-lint.sh --fix <file>...   format and auto-fix the given staged files,
#                                   re-stage them, then fail on leftover issues
#   check-lint.sh --all             check the whole project, applying no fixes
#
# Rule selection and line length live in pyproject.toml ([tool.ruff]).
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HOOK_DIR/common.sh"

mode="check"
case "${1:-}" in
  --fix) mode="fix"; shift ;;
  --all) mode="check"; shift ;;
esac

if ! RUFF=$(resolve_ruff); then
  err "ruff not found. Install dev dependencies: uv sync --extra dev"
  exit 1
fi

if [ "$mode" = "fix" ]; then
  py=()
  for f in "$@"; do
    case "$f" in
      *.py) [ -f "$f" ] && py+=("$f") ;;
    esac
  done
  if [ ${#py[@]} -eq 0 ]; then
    ok "Lint: no staged Python files to check."
    exit 0
  fi

  info "Formatting and auto-fixing ${#py[@]} staged Python file(s)..."
  $RUFF format "${py[@]}"
  $RUFF check --fix "${py[@]}" || true
  # Re-stage whatever the auto-fixers changed so the commit matches what was checked.
  git add -- "${py[@]}"

  fail=0
  $RUFF check "${py[@]}" || fail=1
  $RUFF format --check "${py[@]}" || fail=1
  if [ "$fail" -ne 0 ]; then
    err "Lint check failed (unfixable issues above). Resolve them and re-commit."
    exit 1
  fi
  ok "Lint and format passed."
  exit 0
fi

info "Running strict ruff lint and format check..."
fail=0
$RUFF check || fail=1
$RUFF format --check || fail=1
if [ "$fail" -ne 0 ]; then
  err "Lint/format check failed. Run 'uv run ruff check --fix' and 'uv run ruff format'."
  exit 1
fi
ok "Lint and format passed."
