# Shared helpers for the git hooks under .githooks/.
# Sourced, not executed.

if [ -t 2 ]; then
  _C_RED=$'\033[31m'
  _C_GREEN=$'\033[32m'
  _C_YELLOW=$'\033[33m'
  _C_RESET=$'\033[0m'
else
  _C_RED=""
  _C_GREEN=""
  _C_YELLOW=""
  _C_RESET=""
fi

err()  { printf '%s[ERROR]%s %s\n' "$_C_RED" "$_C_RESET" "$*" >&2; }
ok()   { printf '%s[OK]%s %s\n' "$_C_GREEN" "$_C_RESET" "$*"; }
info() { printf '%s[INFO]%s %s\n' "$_C_YELLOW" "$_C_RESET" "$*"; }

# Echo the command used to invoke ruff, preferring the project's uv env.
# Returns non-zero if ruff cannot be located at all.
resolve_ruff() {
  if command -v uv >/dev/null 2>&1; then
    echo "uv run ruff"
  elif command -v ruff >/dev/null 2>&1; then
    echo "ruff"
  else
    return 1
  fi
}

# Echo the command used to invoke pytest, preferring the project's uv env.
# Returns non-zero if pytest cannot be located at all.
resolve_pytest() {
  if command -v uv >/dev/null 2>&1; then
    echo "uv run pytest"
  elif command -v pytest >/dev/null 2>&1; then
    echo "pytest"
  else
    return 1
  fi
}
