# Scheduler and Unattended Operation

Milestone 7 in `docs/plan.md`.

## Goal

Configure once, then the tool keeps the library clean without attention.

## Tasks

- Interval scheduler (hours, configurable) triggering scans; optional scan-on-startup flag.
- Worker: single background thread, one job at a time; triggers during a job collapse into at most one queued follow-up run.
- Interrupted jobs (restart mid-run) marked interrupted, never resumed; rely on idempotent steps and the next scheduled run.
- Job retention: prune old jobs and results past a configurable limit.
- Long-running subprocess calls (ffmpeg later) run inside the worker without blocking the web app.

## Done When

- Tests cover trigger collapsing, the one-job-at-a-time guarantee, and retention pruning.
- A container left running performs scheduled scans and records them in history.
