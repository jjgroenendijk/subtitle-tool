#!/usr/bin/env bash
# Point this clone at the tracked hooks in .githooks/ and make sure the tools
# they need are available.
#
# Run it once after cloning, and configure it as the setup script for the
# Claude Code web/cloud environment so hooks are active there too. Safe to
# re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/pre-push .githooks/lib/*.sh 2>/dev/null || true
echo "[INFO] core.hooksPath set to .githooks (pre-commit, pre-push active)"

if command -v uv >/dev/null 2>&1; then
  echo "[INFO] Syncing dev dependencies so ruff is available to the hooks..."
  uv sync --extra dev
else
  echo "[WARNING] uv not found; install it so the lint hook can run ruff."
fi

echo "[OK] Git hooks configured."
