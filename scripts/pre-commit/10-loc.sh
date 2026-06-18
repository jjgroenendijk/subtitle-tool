#!/usr/bin/env bash
# Fail when any staged file exceeds the per-file LOC limit (MAX_LOC, default
# 600). Lock files, minified assets and binaries are not hand-written source, so
# skip them.
set -euo pipefail

MAX_LOC="${MAX_LOC:-600}"

violations=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    uv.lock | *.lock | package-lock.json | yarn.lock | poetry.lock) continue ;;
    *.min.js | *.min.css | *.svg) continue ;;
  esac
  grep -Iq . "$f" 2>/dev/null || continue
  loc=$(wc -l <"$f" | tr -d '[:space:]')
  if [ "$loc" -gt "$MAX_LOC" ]; then
    printf '  %s: %s lines (limit %s)\n' "$f" "$loc" "$MAX_LOC" >&2
    violations=$((violations + 1))
  fi
done < <(git diff --cached --name-only --diff-filter=ACM)

if [ "$violations" -gt 0 ]; then
  echo "[ERROR] LOC check failed: $violations file(s) exceed $MAX_LOC lines." >&2
  echo "Split the file(s) above, or set MAX_LOC if larger is genuinely intended." >&2
  exit 1
fi
echo "[OK] LOC check passed (limit $MAX_LOC lines per file)."
