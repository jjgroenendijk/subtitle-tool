#!/usr/bin/env bash
# Strict Stylelint check over all project-owned web UI CSS, applying no fixes.
# Stylelint runs through a single pinned `npx` command (not added to
# package.json and not wired into CI); the config lives at
# tools/stylelint.config.cjs. Only src/subtitle_tool/web/static/css/ is linted;
# vendored assets under static/vendor/ are excluded by the glob, so they are
# never linted as project-owned CSS.
set -euo pipefail

STYLELINT_PIN="stylelint@17.13.0"
CSS_GLOB="src/subtitle_tool/web/static/css/*.css"
CONFIG="tools/stylelint.config.cjs"

# Nothing to do if the project CSS directory is absent or empty.
shopt -s nullglob
existing=(src/subtitle_tool/web/static/css/*.css)
if [ ${#existing[@]} -eq 0 ]; then
  echo "[OK] CSS lint: no project CSS files to check."
  exit 0
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "[ERROR] npx not found. Install Node.js so the CSS lint hook can run Stylelint." >&2
  exit 1
fi

echo "[INFO] Running strict Stylelint check with $STYLELINT_PIN..."
if ! npx -y -p "$STYLELINT_PIN" stylelint --config "$CONFIG" "$CSS_GLOB"; then
  echo "[ERROR] CSS lint failed. Resolve the issues above before pushing." >&2
  exit 1
fi
echo "[OK] CSS lint passed."
