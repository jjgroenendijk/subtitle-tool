#!/usr/bin/env bash
# Run the pytest suite, failing on any test error.
#
# Usage:
#   check-tests.sh --all              run the whole suite
#   check-tests.sh --staged <file>... run the suite only if any given file is a
#                                     Python source or test file, otherwise skip
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

info "Running test suite..."
# shellcheck disable=SC2086 # PYTEST_ARGS is intentionally word-split.
if ! $PYTEST ${PYTEST_ARGS:-}; then
  err "Tests failed. Fix them before committing/pushing (bypass: --no-verify)."
  exit 1
fi
ok "Tests passed."
