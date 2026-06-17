#!/usr/bin/env bash
# Run strict linting and formatting for Python (ruff) and Markdown (mdformat +
# pymarkdown), failing on any unresolved issue.
#
# Usage:
#   check-lint.sh --fix <file>...   format and auto-fix the given staged files
#                                   (Python and Markdown), re-stage them, then
#                                   fail on leftover issues
#   check-lint.sh --all             check the whole project, applying no fixes
#
# Rule selection and line length live in pyproject.toml ([tool.ruff],
# [tool.pymarkdown]); mdformat reads .mdformat.toml. Keeping the thresholds
# there keeps the hooks and CI in sync.
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
if ! MDFORMAT=$(resolve_mdformat); then
  err "mdformat not found. Install dev dependencies: uv sync --extra dev"
  exit 1
fi
if ! PYMARKDOWN=$(resolve_pymarkdown); then
  err "pymarkdown not found. Install dev dependencies: uv sync --extra dev"
  exit 1
fi

if [ "$mode" = "fix" ]; then
  py=()
  md=()
  for f in "$@"; do
    case "$f" in
      *.py) [ -f "$f" ] && py+=("$f") ;;
      *.md) [ -f "$f" ] && md+=("$f") ;;
    esac
  done

  fail=0

  if [ ${#py[@]} -gt 0 ]; then
    info "Formatting and auto-fixing ${#py[@]} staged Python file(s)..."
    $RUFF format "${py[@]}"
    $RUFF check --fix "${py[@]}" || true
    # Re-stage whatever the auto-fixers changed so the commit matches what was checked.
    git add -- "${py[@]}"
    $RUFF check "${py[@]}" || fail=1
    $RUFF format --check "${py[@]}" || fail=1
  fi

  if [ ${#md[@]} -gt 0 ]; then
    info "Formatting ${#md[@]} staged Markdown file(s)..."
    # mdformat reflows to the configured 100-column wrap; pymarkdown only
    # reports, so it is the gate for issues mdformat cannot auto-fix.
    $MDFORMAT "${md[@]}"
    git add -- "${md[@]}"
    $MDFORMAT --check "${md[@]}" || fail=1
    $PYMARKDOWN scan "${md[@]}" || fail=1
  fi

  if [ ${#py[@]} -eq 0 ] && [ ${#md[@]} -eq 0 ]; then
    ok "Lint: no staged Python or Markdown files to check."
    exit 0
  fi

  if [ "$fail" -ne 0 ]; then
    err "Lint check failed (unfixable issues above). Resolve them and re-commit."
    exit 1
  fi
  ok "Lint and format passed."
  exit 0
fi

info "Running strict ruff and Markdown lint and format check..."
fail=0
$RUFF check || fail=1
$RUFF format --check || fail=1
all_md="$(git ls-files '*.md')"
if [ -n "$all_md" ]; then
  # shellcheck disable=SC2086 # word-splitting the tracked .md list is intended.
  $MDFORMAT --check $all_md || fail=1
  # shellcheck disable=SC2086
  $PYMARKDOWN scan $all_md || fail=1
fi
if [ "$fail" -ne 0 ]; then
  err "Lint/format check failed. Run 'uv run ruff check --fix', 'uv run ruff format', and 'uv run mdformat <files>'."
  exit 1
fi
ok "Lint and format passed."
