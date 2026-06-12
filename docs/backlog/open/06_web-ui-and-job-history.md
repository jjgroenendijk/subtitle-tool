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
