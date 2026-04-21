# Subtitle tool

## Docs

- [Architecture](docs/architecture.md): system model, processing flow, skipped-action handling, and extension boundaries.
- [Functional Requirements](docs/functional-requirements.md): user-facing capabilities, configuration options, and UI behavior.
- [Technical Requirements](docs/technical-requirements.md): implementation constraints, runtime behavior, and operational requirements.

Tasks are tracked as markdown files in `docs/backlog/` with the naming convention `<index>_<task-slug>.md`:

- `docs/backlog/open/` - Open tasks awaiting work
- `docs/backlog/pending-review/` - Completed tasks awaiting review
- `docs/backlog/done/` - Completed and reviewed tasks

Move task files between directories as their status changes.
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