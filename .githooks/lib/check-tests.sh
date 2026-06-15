#!/usr/bin/env bash
# Run the pytest suite, failing on any test error.
#
# Usage:
#   check-tests.sh --all              run the whole suite
#   check-tests.sh --staged <file>... run the suite only if any given file is a
#                                     Python source or test file, otherwise skip
#
# Add --coverage (after the mode flag) to also enforce the application-code
# coverage gate. Source paths and the fail_under threshold come from
# pyproject.toml's [tool.coverage] tables, so the hook, CI, and a manual
# `uv run pytest --cov` all share one threshold.
#
# Extra pytest arguments can be supplied via PYTEST_ARGS.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HOOK_DIR/common.sh"

mode="all"
case "${1:-}" in
  --all) mode="all"; shift ;;
  --staged) mode="staged"; shift ;;
esac

coverage=0
if [ "${1:-}" = "--coverage" ]; then
  coverage=1
  shift
fi

if [ "$mode" = "staged" ]; then
  has_py=0
  for f in "$@"; do
    case "$f" in
      *.py) has_py=1; break ;;
    esac
  done
  if [ "$has_py" -eq 0 ]; then
    ok "Tests: no staged Python files, skipping suite."
    exit 0
  fi
fi

if ! PYTEST=$(resolve_pytest); then
  err "pytest not found. Install dev dependencies: uv sync --extra dev"
  exit 1
fi

cov_args=""
if [ "$coverage" -eq 1 ]; then
  info "Running test suite with coverage gate..."
  cov_args="--cov"
else
  info "Running test suite..."
fi
# shellcheck disable=SC2086 # cov_args/PYTEST_ARGS are intentionally word-split.
if ! $PYTEST $cov_args ${PYTEST_ARGS:-}; then
  if [ "$coverage" -eq 1 ]; then
    err "Tests failed or coverage below the threshold in pyproject.toml. Fix before pushing (bypass: --no-verify)."
  else
    err "Tests failed. Fix them before committing/pushing (bypass: --no-verify)."
  fi
  exit 1
fi
ok "Tests passed."
