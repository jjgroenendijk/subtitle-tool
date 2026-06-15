# Git hooks

Tracked hooks that keep the repository green before commits and pushes. They are
not active until this clone is told to use them:

```sh
scripts/setup-githooks.sh
```

That sets `core.hooksPath` to this directory (git ignores a tracked hooks
directory unless pointed at it) and installs the dev dependencies the lint hook
needs. Configure the same script as the setup script for the Claude Code
web/cloud environment so the hooks are active there too.

Hooks

- `pre-commit` - on the staged change set: enforces the per-file LOC limit and
  runs strict ruff linting, auto-formatting and auto-fixing staged Python files
  in place and re-staging them. Blocks the commit on any leftover issue.
- `pre-push` - re-checks the whole tree (LOC limit and strict ruff lint/format,
  no auto-fix), guarding against commits made with the hooks disabled. Blocks
  the push on any failure.

Shared logic lives in `lib/`:

- `check-loc.sh` - fails any file over the limit (default 600 lines, override
  with `MAX_LOC`). Lock files, minified assets and binaries are skipped.
- `check-lint.sh` - runs ruff. Rule selection and line length are defined in
  `pyproject.toml` under `[tool.ruff]`, so the hooks and CI stay in sync.

Bypass in a genuine emergency with `git commit --no-verify` / `git push
--no-verify`. CI runs the same checks, so bypassing only defers them.
