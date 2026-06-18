#!/usr/bin/env bash
# Point this clone at the tracked hooks in .githooks/ and make sure the tools
# they need are available.
#
# Run it once after cloning. For cloud environments (Claude Code on the web,
# Codex cloud) use scripts/setup-cloud.sh instead, which installs system deps
# and then calls this script. Safe to re-run. Works whether invoked by path
# (./scripts/setup-githooks.sh) or pasted inline, as long as the working
# directory is inside the repository.
set -euo pipefail

# Locate the repository root. Prefer git's own answer so this works even when
# the script is run inline (no real $BASH_SOURCE path); fall back to the
# script's location for the run-by-path case.
if root=$(git rev-parse --show-toplevel 2>/dev/null); then
  cd "$root"
elif [ -f "${BASH_SOURCE[0]:-}" ]; then
  cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  echo "[ERROR] not inside a git repository; run this from within the repo" >&2
  exit 1
fi

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/pre-push \
  scripts/pre-commit/*.sh scripts/pre-push/*.sh 2>/dev/null || true
echo "[INFO] core.hooksPath set to .githooks (pre-commit, pre-push active)"

if command -v uv >/dev/null 2>&1; then
  echo "[INFO] Syncing dev dependencies so ruff, mdformat, and pymarkdown are available to the hooks..."
  uv sync --extra dev
else
  echo "[WARNING] uv not found; install it so the lint hook can run ruff, mdformat, and pymarkdown."
fi

echo "[OK] Git hooks configured."
