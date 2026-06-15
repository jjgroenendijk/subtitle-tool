#!/usr/bin/env bash
# Fail when any checked file exceeds the per-file line limit.
#
# Usage:
#   check-loc.sh --all          check every tracked file
#   check-loc.sh <file>...       check only the given files
#
# The limit defaults to 600 and can be overridden with MAX_LOC.
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HOOK_DIR/common.sh"

MAX_LOC="${MAX_LOC:-600}"

files=()
if [ "${1:-}" = "--all" ]; then
  while IFS= read -r f; do files+=("$f"); done < <(git ls-files)
else
  files=("$@")
fi

# Generated, vendored or lock files are not hand-written source; skip them.
should_skip() {
  case "$1" in
    uv.lock | *.lock | package-lock.json | yarn.lock | poetry.lock) return 0 ;;
    *.min.js | *.min.css | *.svg) return 0 ;;
  esac
  return 1
}

violations=0
for f in ${files[@]+"${files[@]}"}; do
  [ -f "$f" ] || continue
  should_skip "$f" && continue
  # Skip binary files (grep -I reports no match for binary content).
  grep -Iq . "$f" 2>/dev/null || continue
  loc=$(wc -l <"$f" | tr -d '[:space:]')
  if [ "$loc" -gt "$MAX_LOC" ]; then
    printf '  %s: %s lines (limit %s)\n' "$f" "$loc" "$MAX_LOC" >&2
    violations=$((violations + 1))
  fi
done

if [ "$violations" -gt 0 ]; then
  err "LOC check failed: $violations file(s) exceed $MAX_LOC lines."
  echo "Split the file(s) above, or set MAX_LOC if larger is genuinely intended." >&2
  exit 1
fi

ok "LOC check passed (limit $MAX_LOC lines per file)."
