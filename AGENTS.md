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

## Project Layout

- `src/subtitle_tool/` - the package.
  - `config/` - bootstrap env settings (`BootstrapSettings`) and the persisted
    TOML config model plus loader/validation.
  - `web/` - FastAPI app factory (`create_app`); currently a `/health` stub.
  - `__main__.py` - console entry point (`subtitle-tool`) serving the app.
- `tests/` - pytest suite mirroring the package.
- `docs/` - architecture, requirements, plan, and the backlog (see below).
- `Dockerfile`, `docker/entrypoint.sh`, `docker-compose.yml` - container image
  bundling ffmpeg, dropping to PUID/PGID via gosu.
- `.github/workflows/` - `ci.yml` (ruff + pytest), `docker.yml` (image build and
  GHCR publish).

## Development

The project uses [uv](https://docs.astral.sh/uv/).

```sh
uv sync --extra dev          # create or update the environment
uv run pytest                # run the tests
uv run ruff check            # lint
uv run ruff format --check   # check formatting (drop --check to apply)
```

Bootstrap settings come from environment variables only: `CONFIG_DIR`, `PORT`,
`PUID`, `PGID`, `TZ`. Everything else lives in the TOML config file under
`CONFIG_DIR` and is validated on load.

## Docs

- [Architecture](docs/architecture.md): operating model, components, pipeline, safety rules, and technology choices.
- [Functional Requirements](docs/functional-requirements.md): user-facing capabilities and configuration behavior.
- [Technical Requirements](docs/technical-requirements.md): implementation constraints, runtime behavior, and operational requirements.
- [Plan](docs/plan.md): implementation milestones; detailed tasks live in `docs/backlog/open/`.

Tasks are tracked as markdown files in `docs/backlog/` with the naming convention `<index>_<task-slug>.md`:

- `docs/backlog/open/` - Open tasks awaiting work
- `docs/backlog/pending-review/` - Completed tasks awaiting review
- `docs/backlog/done/` - Completed and reviewed tasks

Move task files between directories as their status changes.

Milestones build on each other and each ends in a working, tested, shippable
state. After completing a milestone, update this AGENTS.md so the Project Layout,
Development, and any changed conventions reflect the new reality; a stale
AGENTS.md is a defect. Move the milestone's backlog file out of `open/` in the
same change.

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

## Writing Style

Maximize information density, while making text effortless to read
Never use bold formatting in markdown text, unless the info is absolutely critical
NEVER use emojis anywhere, but rather use [ERROR], [WARNING], [INFO] or something else in brackets
Keep markdown and text headings unnumbered