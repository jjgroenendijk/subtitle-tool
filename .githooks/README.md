# Git hooks

Tracked hooks that keep the repository green before commits and pushes. They are not active until
this clone is told to use them:

```sh
scripts/setup-githooks.sh
```

That sets `core.hooksPath` to `.githooks/hooks` (git ignores a tracked hooks directory unless
pointed at it) and installs the dev dependencies the lint hook needs. Configure the same script as
the setup script for the Claude Code web/cloud environment so the hooks are active there too.

Layout: the entrypoints in `.githooks/hooks/<hook>` are tiny runners only; each executes every
executable `*.sh` script in the matching `.githooks/<hook>/` directory, in name order, forwards the
hook args, and aborts on the first non-zero exit. The checks themselves are the individual scripts,
each standalone (no shared library to trace through). Add or drop a check by adding or removing a
script.

- `pre-commit` runs `.githooks/pre-commit/` on the staged change set: `10-loc.sh` enforces the
  per-file LOC limit, `20-lint.sh` formats and auto-fixes staged Python with ruff and staged
  Markdown with mdformat (re-staging the result), `30-tests.sh` runs the test suite when the commit
  touches any Python file, and `40-css.sh` Stylelints staged project CSS. Blocks the commit on any
  leftover issue.
- `pre-push` runs `.githooks/pre-push/` over the whole tree: `10-loc.sh` enforces the LOC limit,
  `20-lint.sh` runs strict ruff and Markdown lint/format with no auto-fix, `30-tests.sh` runs the
  full test suite with the coverage gate, and `40-css.sh` Stylelints all project CSS. This guards
  against commits made with the hooks disabled, and blocks the push on any failure or when
  application-code coverage falls below the threshold.

Shared behavior:

- LOC limit defaults to 600 lines per file; override with `MAX_LOC`. Lock files, minified assets and
  binaries are skipped.
- Ruff rules and line length live in `pyproject.toml` under `[tool.ruff]`; mdformat reads
  `.mdformat.toml` and pymarkdown reads `[tool.pymarkdown]`, so the hooks and CI stay in sync.
- The `pre-push` coverage gate runs `pytest --cov`; the source paths and the `fail_under` threshold
  come from `pyproject.toml`'s `[tool.coverage]` tables. Pass extra arguments to either hook's
  pytest run via `PYTEST_ARGS`.

Bypass in a genuine emergency with `git commit --no-verify` / `git push --no-verify`. CI runs the
same checks, so bypassing only defers them.
