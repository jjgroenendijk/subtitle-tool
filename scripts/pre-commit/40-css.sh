#!/usr/bin/env bash
# Lint staged project-owned web UI CSS with Stylelint. Runs only when files under
# src/subtitle_tool/web/static/css/ are staged, so non-CSS commits pay nothing.
# Stylelint runs through a single pinned `npx` command (not added to
# package.json and not wired into CI); the config lives at
# tools/stylelint.config.cjs. Vendored assets under static/vendor/ are never
# linted as project-owned CSS, so they are filtered out here.
set -euo pipefail

# Pin Stylelint so the hook and any docs stay on one known version.
STYLELINT_PIN="stylelint@17.13.0"
CSS_DIR="src/subtitle_tool/web/static/css"
CONFIG="tools/stylelint.config.cjs"

css=()
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    "$CSS_DIR"/*.css) css+=("$f") ;;
  esac
done < <(git diff --cached --name-only --diff-filter=ACM)

if [ ${#css[@]} -eq 0 ]; then
  echo "[OK] CSS lint: no staged project CSS files to check."
  exit 0
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "[ERROR] npx not found. Install Node.js so the CSS lint hook can run Stylelint." >&2
  exit 1
fi

echo "[INFO] Linting ${#css[@]} staged CSS file(s) with $STYLELINT_PIN..."
if ! npx -y -p "$STYLELINT_PIN" stylelint --config "$CONFIG" "${css[@]}"; then
  echo "[ERROR] CSS lint failed (issues above). Resolve them and re-commit." >&2
  exit 1
fi
echo "[OK] CSS lint passed."
