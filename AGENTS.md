# Subtitle tool

Self-hosted tool that keeps the subtitle side of a Plex media library clean:
external UTF-8 SRT files, correct language codes in filenames Plex understands,
junk lines removed, and embedded subtitles extracted where wanted. Configured
once through a web UI, then runs unattended. Hobby tool: favor a small codebase,
few moving parts, and behavior that is easy to reason about over configurability.

One process, one container: a FastAPI web app, a scheduler, an inotify watcher, a
single-job worker, a scanner, and an idempotent file pipeline. There is no
per-file state database; the filesystem is the source of truth. Persisted state
is one TOML config file and a SQLite job history, both under `/config`. See
[docs/architecture.md](docs/architecture.md) for the full design.

```mermaid
flowchart LR
    subgraph triggers["Worker-backed triggers"]
        sched["scheduler"]
        watch["watcher (inotify)"]
        ui["web UI button"]
    end
    triggers --> worker["single-job worker"]
    worker --> scanner["scanner"]
    scanner --> index["media index (reconcile)"]
    index --> pipeline["file pipeline (video + per-file steps)"]
    pipeline --> broker["event broker"]
    broker --> sse["SSE"] --> web["web UI / dashboard"]
    cli["cli scan"] -.->|direct: no worker / index / history / SSE| pipeline
    cfg[("/config: config.toml, jobs.db, index.db")] -.-> worker
    index -.-> cfg
```

## Project Layout

- `src/subtitle_tool/` - the package. See `src/subtitle_tool/CLAUDE.md` for the
  subpackage map, the scan data flow, and package-editing invariants.
- `tests/` - pytest suite mirroring the package.
- `docs/` - architecture and requirements (see below).
- `frontend/` - npm manifest, lockfile, and `refresh-alpine.mjs` that pin
  Alpine.js and refresh the vendored static asset. Dependency-tracking and
  vendor-refresh tooling only (so Dependabot can watch Alpine and `npm run
  vendor` can update the committed file); not a runtime or application build
  step. `frontend/node_modules/` is gitignored.
- `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml` - container image
  bundling ffmpeg, dropping to PUID/PGID via gosu.
- `.github/workflows/` - `ci.yml` (ruff + pytest with coverage gate),
  `docker.yml` (image build and GHCR publish).

## Development

The project uses [uv](https://docs.astral.sh/uv/).

```sh
uv sync --extra dev          # create or update the environment
uv run pytest                # run the tests
uv run pytest --cov          # run the tests with the coverage gate
uv run ruff check            # lint
uv run ruff format --check   # check formatting (drop --check to apply)
```

`uv run pytest --cov` measures coverage for the application package only
(`src/subtitle_tool`) and fails when it drops below the `fail_under` threshold
in `pyproject.toml`'s `[tool.coverage.report]`. CI and the `pre-push` git hook
run this same gate, so the threshold lives in one place.

Bootstrap settings come from environment variables only: `CONFIG_DIR`, `PORT`,
`PUID`, `PGID`, `TZ`, `BROWSE_ROOT` (the root the config UI directory picker is
confined to, default `/`). Everything else lives in the TOML config file under
`CONFIG_DIR` and is validated on load.

Run the web UI (the default command) or a one-off scan from the CLI:

```sh
uv run subtitle-tool                                 # serve the web UI on PORT
uv run subtitle-tool scan /path/to/media --dry-run   # report planned actions
uv run subtitle-tool scan /path/to/media             # apply changes
uv run subtitle-tool scan --config /config/config.toml
```

The UI configures the tool (config page), triggers scans (dashboard buttons),
streams live job progress over Server-Sent Events, and shows job history from the
SQLite store under `CONFIG_DIR`. Scans run on a single background worker.

The web UI stack is server-rendered Jinja/FastAPI as the source of truth, with
Alpine.js as a thin local-interaction layer for page-local state only (config
language and directory pickers, library "show gaps only" toggle). This is an
intentional part of the stack, not an accident to refactor away. Preserve the
split: keep navigation, persistence, and validation server-side; use named
`Alpine.data(...)` components in `app.js` for transient in-page interactivity;
do not turn the UI into an SPA or add a frontend bundler/build step. Alpine is
the pinned `@alpinejs/csp` build vendored under
`src/subtitle_tool/web/static/vendor/`; because the CSP build forbids inline
expression evaluation, keep template expressions to property/method references
and put logic in the components. To bump it, let Dependabot update
`frontend/package.json`/`package-lock.json`, then run `npm ci && npm run vendor`
from `frontend/` to refresh the committed static asset. Do not add Alpine as a
Git submodule.

## Docs

- [Architecture](docs/architecture.md): operating model, components, pipeline, safety rules, and technology choices.
- [Functional Requirements](docs/functional-requirements.md): user-facing capabilities and configuration behavior.
- [Technical Requirements](docs/technical-requirements.md): implementation constraints, runtime behavior, and operational requirements.

When a change alters behavior, update this AGENTS.md so the Project Layout,
Development, and any changed conventions reflect the new reality; a stale
AGENTS.md is a defect.

ALWAYS keep track of troubleshooting progress in a troubleshooting case file in docs/troubleshooting/<DATE>_<SUBJECT>.md.
While troubleshooting, append the steps taken to the troubleshooting case file. For example, `echo 'pinged 1.1.1.1, ping is ok' >> docs/troubleshooting/<DATE>_<SUBJECT>.md`

## Git

Commit in small increments, but no meaningless micro-commits. "WIP"/vague messages forbidden. Checkpoints must stay local or on scratch branch until green and reviewable. Before PR/merge: rebase/squash to atomic, green, conventional, documentation-grade commits.
Each commit must contain one logical change only. Do not mix unrelated changes, refactors with behavior changes, or formatting with functional changes. Each commit must be independently checkable and in working state.
Required Commit Body Sections for non-trivial commits:
- Context: What problem/need triggered this
- Change: High-level summary of what changed
- Rationale: Why this approach, trade-offs, alternatives rejected
- Impact/Risk: Behavior changes, migrations, compatibility, performance
- Tests: Exact command(s) run (e.g., `Tests: cd src && uv run pytest tests/`)
Subject: imperative mood ("add", "fix"), ~50 chars, no period.

Body: blank line after subject, explain what/why (not how), wrap ~72 chars. Body required for non-trivial changes.
Use Conventional Commits format: `type(scope?): subject`

Allowed types: `feat, fix, docs, refactor, test, perf, build, ci, chore, style, revert`

Breaking changes: use `type(scope)!: subject` OR `BREAKING CHANGE: ...` footer with migration steps.
MUST NOT add author/co-author attribution trailers for AI. Forbidden: `Co-authored-by:`, `Generated-by:`, `AI-Generated-by:`, `Assisted-by:`, `Model:`. Allowed trailers: `Fixes #...`, `Refs #...`, `BREAKING CHANGE:...`, `Signed-off-by:` (human only).
MUST run tests before every commit (minimum: fast suite or targeted tests for changed area). EACH COMMIT MUST KEEP REPO GREEN: build passes, tests pass. Failing commits are forbidden on shared branches. Intermediate failing steps must stay local and be squashed before PR/merge.
Every PR MUST reference a GitHub issue whenever one applies, using a closing keyword (`Fixes #...`, `Closes #...`, `Resolves #...`) in the PR body so the issue closes automatically on merge.

## Writing Style

Maximize information density, while making text effortless to read
Never use bold formatting in markdown text, unless the info is absolutely critical
NEVER use emojis anywhere, but rather use [ERROR], [WARNING], [INFO] or something else in brackets
Keep markdown and text headings unnumbered