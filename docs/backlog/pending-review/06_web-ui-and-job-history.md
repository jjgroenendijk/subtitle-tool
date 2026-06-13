# Web UI and Job History

Milestone 6 in `docs/plan.md`.

## Goal

Configure and operate the tool entirely from the browser.

## Tasks

- FastAPI app with server-rendered templates (Jinja2) and a small JSON API; no build step, minimal JavaScript.
- Configuration page: form for all settings, validation feedback, atomic write to the config file; changes apply on next run.
- SQLite store for jobs, per-file results, and warnings.
- SSE endpoint streaming job events (job started, file processed, warnings, job finished) from the worker to connected browsers; pages subscribe with `EventSource`.
- Dashboard: current job progress updated live via SSE, recent jobs, scan-now buttons for dry-run and real mode.
- Job detail page: per-file actions taken, skipped actions with reasons, errors; updates live while the job runs.
- Health endpoint returning app status.

## Done When

- API tests for config round-trip, job creation, and history retrieval.
- A manual scan triggered from the UI runs in the background while the UI stays responsive.

## Outcome

Implemented on branch `claude/quirky-newton-cikdfw`.

- Config writing: `config.save_config` serialises a `Config` to TOML (`tomli-w`)
  through the same temp-file-plus-atomic-replace discipline the pipeline uses.
- New `jobs/` package: `JobStore` (SQLite history of jobs and per-file results,
  one lock-guarded connection, retention pruning, summary counts on the job row);
  `EventBroker` (in-memory pub/sub bridging the worker thread to async SSE
  subscribers via `call_soon_threadsafe`); `Worker` (one scan at a time on a daemon
  thread, recording each touched file and publishing
  `job_started`/`file_processed`/`job_finished` events). Only files with actions,
  warnings, or an error are stored, keeping history compact.
- `run_pipeline` gained an optional `on_file` progress callback and `ScanResult` a
  `subtitle_count`, so the worker reports live progress.
- Web app (`web/`): dashboard with dry-run and apply scan buttons, recent jobs, and
  a live SSE progress panel; job detail page with per-file actions, warnings, and
  errors that updates live; configuration page generated from the config model
  (every setting covered, validation feedback, atomic write); `/events` SSE stream
  (extracted to `sse.py` as a testable async generator); a JSON API
  (`/api/config`, `/api/jobs`) for config round-trip and job creation/history; the
  existing `/health` probe. Server-rendered Jinja2 templates plus one vanilla-JS
  file; no build step. Added `jinja2` and `python-multipart` dependencies.
- Tests: `tests/jobs/` (store, broker, worker), `tests/test_sse.py`,
  `tests/test_web.py` (pages, config round-trip via form and JSON API, job creation
  and history, background scan staying responsive, validation errors, 404s), and
  config writer round-trip tests.
- `Tests: uv run pytest` (138 passed), `uv run ruff check`,
  `uv run ruff format --check`.
