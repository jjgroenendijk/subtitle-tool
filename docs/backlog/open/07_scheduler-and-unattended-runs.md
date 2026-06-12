# Scheduler, Watcher, and Unattended Operation

Milestone 7 in `docs/plan.md`.

## Goal

Configure once, then the tool keeps the library clean without attention, including new downloads as they arrive.

## Tasks

- Interval scheduler (hours, configurable) triggering scans; optional scan-on-startup flag.
- Filesystem watcher (watchdog/inotify) on the media paths, enabled by default and toggleable in configuration.
- Watcher debounce: queue a file only after its size and mtime have been stable for a configurable window, so in-progress copies and downloads are never touched.
- Watcher triggers queue a scan scoped to the changed directories through the normal discovery and pipeline flow; raw events are never acted on directly.
- Worker: single background thread, one job at a time; triggers during a job collapse into at most one queued follow-up run, with watcher scopes merged into that run.
- Interrupted jobs (restart mid-run) marked interrupted, never resumed; rely on idempotent steps and the next scheduled run.
- Job retention: prune old jobs and results past a configurable limit.
- Long-running subprocess calls (ffmpeg later) run inside the worker without blocking the web app.

## Done When

- Tests cover trigger collapsing, the one-job-at-a-time guarantee, watcher debounce and stability behavior (using temporary directories and simulated slow copies), scope merging, and retention pruning.
- A container left running performs scheduled scans, and a file copied into a watched path is processed shortly after the copy completes.
