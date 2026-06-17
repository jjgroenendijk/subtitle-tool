#!/usr/bin/env bash
# One-shot bootstrap for cloud coding environments (Claude Code on the web and
# Codex cloud). Installs the system and Python dependencies the test suite needs
# but the base images do not ship, then wires up the tracked git hooks.
#
# Use it as the environment's setup script:
#   - Claude Code (web): environment settings -> Setup script field, enter
#       bash scripts/setup-cloud.sh
#   - Codex cloud: Settings -> Environments -> Setup script, enter
#       bash scripts/setup-cloud.sh
#
# Both run their setup script as root on Ubuntu with network access, then cache
# the resulting filesystem, so everything installed here is present at the start
# of every session without re-running. Safe to re-run; each step is idempotent.
set -euo pipefail

# Locate the repository root so the script works by path or pasted inline.
if root=$(git rev-parse --show-toplevel 2>/dev/null); then
  cd "$root"
elif [ -f "${BASH_SOURCE[0]:-}" ]; then
  cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  echo "[ERROR] not inside a git repository; run this from within the repo" >&2
  exit 1
fi

# Run a command as root when not already root (cloud setup runs as root; a
# local invocation may not). Falls back to plain execution if sudo is absent.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

# ffmpeg/ffprobe: required by the video pipeline and its integration tests.
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "[INFO] ffmpeg already present; skipping install."
elif command -v apt-get >/dev/null 2>&1; then
  echo "[INFO] Installing ffmpeg via apt..."
  as_root apt-get update
  as_root apt-get install -y --no-install-recommends ffmpeg
else
  echo "[WARNING] ffmpeg missing and apt-get unavailable; install it manually." >&2
fi

# uv: pre-installed on both images, but install it if a base image lacks it.
if ! command -v uv >/dev/null 2>&1; then
  echo "[INFO] uv not found; installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[INFO] Syncing dependencies (incl. dev extras)..."
uv sync --extra dev

# Playwright browser + its OS libraries, for browser-based tests. --with-deps
# installs the required apt packages, so it needs root (true in cloud setup).
echo "[INFO] Installing Playwright Chromium and OS dependencies..."
if [ "$(id -u)" -eq 0 ]; then
  uv run playwright install --with-deps chromium
else
  # Non-root: install the browser; OS deps may need a manual --with-deps later.
  uv run playwright install chromium || \
    echo "[WARNING] playwright browser install failed; rerun as root with --with-deps." >&2
fi

# Tracked git hooks (core.hooksPath + chmod + dev sync).
echo "[INFO] Configuring git hooks..."
bash scripts/setup-githooks.sh

echo "[OK] Cloud environment setup complete."
