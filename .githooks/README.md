# Git hooks

Tracked hooks that keep the repository green before commits and pushes. They are not active until
this clone is told to use them:

```sh
scripts/setup-githooks.sh
```

That sets `core.hooksPath` to this directory (git ignores a tracked hooks directory unless pointed
at it) and installs the dev dependencies the lint hook needs. Configure the same script as the setup
script for the Claude Code web/cloud environment so the hooks are active there too.

Hooks

- `pre-commit` - on the staged change set: enforces the per-file LOC limit, runs strict ruff linting
  (auto-formatting and auto-fixing staged Python files in place and re-staging them), and formats
  staged Markdown with mdformat, then runs the test suite when the commit touches any Python file.
  Blocks the commit on any leftover issue.
- `pre-push` - re-checks the whole tree (LOC limit, strict ruff and Markdown lint/format with no
  auto-fix, and the full test suite with the coverage gate), guarding against commits made with the
  hooks disabled. Blocks the push on any failure or when application-code coverage falls below the
  threshold.

Shared logic lives in `lib/`:

- `check-loc.sh` - fails any file over the limit (default 600 lines, override with `MAX_LOC`). Lock
  files, minified assets and binaries are skipped.
- `check-lint.sh` - runs ruff for Python and mdformat + pymarkdown for Markdown. Ruff rules and line
  length live in `pyproject.toml` under `[tool.ruff]`; mdformat reads `.mdformat.toml` and
  pymarkdown reads `[tool.pymarkdown]`, so the hooks and CI stay in sync.
- `check-tests.sh` - runs `pytest`. `--all` runs the whole suite; `--staged` runs it only when a
  staged file is Python. Add `--coverage` (used by `pre-push`) to also enforce the application-code
  coverage gate; the source paths and the `fail_under` threshold come from `pyproject.toml`'s
  `[tool.coverage]` tables. Pass extra arguments via `PYTEST_ARGS`.

Bypass in a genuine emergency with `git commit --no-verify` / `git push --no-verify`. CI runs the
same checks, so bypassing only defers them.
