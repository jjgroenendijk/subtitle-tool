# Subtitle Tool — Architecture

## Context

The Subtitle Tool is a small self-hosted application for a Linux server running Plex. It keeps the subtitle side of a media library clean: external UTF-8 SRT files, correct language codes in filenames Plex understands, junk lines removed, and embedded subtitles extracted where wanted.

It is a hobby tool, not an enterprise product. The architecture favors a small codebase, few moving parts, and behavior that is easy to reason about over configurability and abstraction.

## Operating Model

The tool is configured once through a web interface and then runs unattended.

1. The user starts the container, opens the web UI, points the tool at one or more media paths, and adjusts settings.
2. A scheduler triggers scans at a configured interval, and a filesystem watcher triggers a scoped scan when new or changed files appear, so a fresh download is processed without waiting for the next interval. The user can also trigger a scan manually from the UI.
3. Each scan walks the media paths (or just the changed paths for watcher-triggered scans), reconciles what it finds against the media index, skips files unchanged since the last scan, then decides what work the remaining files need and processes it.
4. The UI shows job history, per-file results, warnings for anything the tool skipped because it was unsure, and the indexed library with its subtitle languages and missing-language gaps.

There is no separate plan-review or approval workflow. Safety comes from two things instead: a dry-run mode that reports what a scan would do without touching files, and conservative defaults (destructive options are off until enabled).

## Media Index as Tracked State

The tool keeps a SQLite media index recording every discovered video and subtitle. Each scan reconciles the filesystem against this index: a file whose fingerprint (size and mtime) matches its row is skipped, new or changed files are processed, and rows for files that have vanished are marked gone. Reconciliation loads the existing rows once and classifies the inventory in memory, writing the changes in batched passes, so a large library does not issue a query per discovered file. The index is authoritative for deciding what work a scan does, and it lets the UI show the library and report which videos are missing a wanted subtitle language without re-walking the disk.

The pipeline can rename, rewrite, delete, or extract files after this pre-pipeline reconcile, so when a real job finishes the worker re-reconciles just the directories it changed, scoped so files outside them are never judged gone. That keeps the index reflecting the final filesystem state immediately rather than lagging until the next full scan; a dry run writes nothing and skips this refresh.

Idempotency is kept as a safety net rather than the decision mechanism. Every pipeline step is still idempotent and every file write is atomic, so a stale or rebuilt index can never cause a harmful action. The index is fully rebuildable: delete it and a clean full scan repopulates it.

Persisted state lives in a single mounted `/config` volume:

- One configuration file, edited through the web UI.
- `jobs.db`: a SQLite database for job history, per-file results, and warnings.
- `index.db`: a SQLite database for the media index of videos and subtitles.

## Components

One process, one container, seven small parts:

- Web app: serves the UI and a small JSON API for configuration, triggering scans, reading job history, and browsing the media index.
- Scheduler: triggers a scan on a configured interval; optional scan on startup.
- Watcher: inotify-based filesystem watcher on the media paths. It reacts only to mutation events (create, modify, move) and ignores read/open/close events, so a scan reading files cannot trigger another scan. It debounces the events it does act on and waits until a new file's size is stable (so half-copied downloads are not touched), then queues a scan scoped to the changed directories. The watcher only ever triggers the normal scan-and-pipeline flow; it never acts on raw events directly.
- Worker: runs one job at a time in the background so long ffmpeg or sync operations never block the UI. Triggers that arrive while a job runs are collapsed into a single follow-up run. A user can stop the running job from the UI; the worker observes the stop at the next file boundary, records the job as `cancelled`, and drops any queued follow-up.
- Scanner: walks media paths, applies exclude patterns, finds videos and subtitle files, and pairs subtitles with videos using filename matching.
- Indexer: reconciles the scan inventory with `index.db`. It records video and subtitle rows (path, fingerprint, parsed language and flags, subtitle-to-video match status, and first-seen/last-seen/last-changed timestamps), reports which wanted languages a video is missing, and keeps a change history for audit.
- Pipeline: applies the processing steps to each video group or standalone subtitle file the index marks as new or changed.

## Pipeline

For each video that needs work, the video phase runs first when enabled:

1. Inspect embedded subtitle streams with ffprobe.
2. Extract wanted text-based streams to external files.
3. Optionally remux the video to drop extracted streams (off by default).

Then the subtitle phase runs per subtitle file, in dependency order:

1. Encoding normalization to UTF-8.
2. Language detection.
3. Language filtering (delete or keep-and-warn unwanted languages; off by default).
4. Format conversion (ASS/SSA/VTT to SRT).
5. Content cleanup (ads, watermarks, empty blocks, artifacts).
6. Filename normalization to Plex conventions (`Movie (2020).en.srt`, `.en.sdh.srt`, `.en.forced.srt`).
7. Sync correction of video-matched SRT subtitles against the video's audio track via ffsubsync, off by default and gated on offset, score, and shift thresholds.

Each step can be toggled in the configuration. Failure on one file is recorded and does not stop the job.

## Safety Rules

These are the few rules the whole tool is built around:

- When the tool cannot make a confident decision (ambiguous subtitle-to-video match, low-confidence language detection, uncertain sync result), it skips the action and records a warning explaining why. It never guesses on a destructive action.
- Anything that rewrites a file writes to a temporary file next to the target, validates the result, and replaces atomically. A failure leaves the original untouched, and the run reports the file as skipped (with a warning) rather than counting it as changed.
- Deleting originals (after extraction, conversion, or language filtering) is always opt-in and off by default.
- Dry-run mode runs the full scan and pipeline decision logic and reports planned actions without modifying anything.

## Technology Choices

- Python 3.12+, because the relevant ecosystem lives there: `pysubs2` (parsing/conversion), `charset-normalizer` (encoding), `lingua` (language detection), `ffsubsync` (sync correction).
- FastAPI with server-rendered templates and minimal JavaScript for the web UI. Job progress is pushed to the browser over Server-Sent Events: one-way push fits the use case, the browser `EventSource` API reconnects automatically, and it avoids the protocol overhead of WebSockets.
- SQLite via the standard library for job history (`jobs.db`) and the media index (`index.db`), each in its own file under `/config`. No external services.
- ffmpeg/ffprobe bundled in the container image for stream inspection, extraction, and remuxing.
- The worker is a background thread guarded by a lock; one job at a time per container. Parallelism and multi-container coordination are out of scope.

## Deployment

- Single Docker container, Linux only, published to GitHub Container Registry by GitHub Actions on tagged releases.
- The image bundles ffmpeg and all Python dependencies; nothing is required on the host.
- Volumes: `/config` for state, media paths mounted read-write wherever the user prefers.
- PUID/PGID environment variables for file-ownership compatibility with Plex setups.
- Environment variables cover bootstrap concerns only (port, config directory, PUID/PGID, timezone, and the directory-picker root). Everything else is configured in the web UI and persisted to the config file.
- Split health endpoints: `/health/live` for container liveness (the process is up)
  and `/health/ready` for readiness (config directory and SQLite stores are usable);
  `/health` is kept as a deprecated liveness alias. Runtime events are logged to
  stdout as structured JSON lines for container log aggregation.

## Testing

- Unit tests (pytest) for every pipeline step using small fixture subtitle files; these make up the bulk of the suite since steps are pure file-in/file-out transformations.
- Scanner and matching tests against temporary directory trees.
- An integration test that runs a full scan in dry-run and real mode against a fixture library, asserting filesystem end state.
- CI runs lint (ruff) and tests on every push; the container build runs on every push and publishes on tags.

## Deferred

Not in scope until the core is solid: OCR for image-based subtitles, downloading subtitles from external providers, notifications, authentication (the tool assumes a trusted home network), and translations (UI is English only).
