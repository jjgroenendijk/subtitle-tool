# Subtitle Tool — Architecture

## Context

The Subtitle Tool is a small self-hosted application for a Linux server running Plex. It keeps the subtitle side of a media library clean: external UTF-8 SRT files, correct language codes in filenames Plex understands, junk lines removed, and embedded subtitles extracted where wanted.

It is a hobby tool, not an enterprise product. The architecture favors a small codebase, few moving parts, and behavior that is easy to reason about over configurability and abstraction.

## Operating Model

The tool is configured once through a web interface and then runs unattended.

1. The user starts the container, opens the web UI, points the tool at one or more media paths, and adjusts settings.
2. A scheduler triggers scans at a configured interval. The user can also trigger a scan manually from the UI.
3. Each scan walks the media paths, decides what work each file needs, and processes it.
4. The UI shows job history, per-file results, and warnings for anything the tool skipped because it was unsure.

There is no separate plan-review or approval workflow. Safety comes from two things instead: a dry-run mode that reports what a scan would do without touching files, and conservative defaults (destructive options are off until enabled).

## Idempotent Processing Instead of Tracked State

The tool does not keep a per-file processing database. Every pipeline step is idempotent: a file that is already in good shape produces no actions. Rescanning a clean library is cheap and changes nothing, so the filesystem itself is the source of truth.

Persisted state is limited to:

- One configuration file, edited through the web UI.
- A SQLite database for job history, per-file results, and warnings.

Both live in a single mounted `/config` volume.

## Components

One process, one container, five small parts:

- Web app: serves the UI and a small JSON API for configuration, triggering scans, and reading job history.
- Scheduler: triggers a scan on a configured interval; optional scan on startup.
- Worker: runs one job at a time in the background so long ffmpeg or sync operations never block the UI. Triggers that arrive while a job runs are collapsed into a single follow-up run.
- Scanner: walks media paths, applies exclude patterns, finds videos and subtitle files, and pairs subtitles with videos using filename matching.
- Pipeline: applies the processing steps to each video group or standalone subtitle file.

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
7. Sync correction against the video's audio track (later milestone, off by default).

Each step can be toggled in the configuration. Failure on one file is recorded and does not stop the job.

## Safety Rules

These are the few rules the whole tool is built around:

- When the tool cannot make a confident decision (ambiguous subtitle-to-video match, low-confidence language detection, uncertain sync result), it skips the action and records a warning explaining why. It never guesses on a destructive action.
- Anything that rewrites a file writes to a temporary file next to the target, validates the result, and replaces atomically. A failure leaves the original untouched.
- Deleting originals (after extraction, conversion, or language filtering) is always opt-in and off by default.
- Dry-run mode runs the full scan and pipeline decision logic and reports planned actions without modifying anything.

## Technology Choices

- Python 3.12+, because the relevant ecosystem lives there: `pysubs2` (parsing/conversion), `charset-normalizer` (encoding), `lingua` (language detection), `ffsubsync` (sync, later).
- FastAPI with server-rendered templates and minimal JavaScript for the web UI. Job progress is shown by polling, not WebSockets.
- SQLite via the standard library for job history. No external services.
- ffmpeg/ffprobe bundled in the container image for stream inspection, extraction, and remuxing.
- The worker is a background thread guarded by a lock; one job at a time per container. Parallelism and multi-container coordination are out of scope.

## Deployment

- Single Docker container, Linux only, published to GitHub Container Registry by GitHub Actions on tagged releases.
- The image bundles ffmpeg and all Python dependencies; nothing is required on the host.
- Volumes: `/config` for state, media paths mounted read-write wherever the user prefers.
- PUID/PGID environment variables for file-ownership compatibility with Plex setups.
- Environment variables cover bootstrap concerns only (port, config directory, PUID/PGID, timezone). Everything else is configured in the web UI and persisted to the config file.
- Health endpoint for container liveness checks.

## Testing

- Unit tests (pytest) for every pipeline step using small fixture subtitle files; these make up the bulk of the suite since steps are pure file-in/file-out transformations.
- Scanner and matching tests against temporary directory trees.
- An integration test that runs a full scan in dry-run and real mode against a fixture library, asserting filesystem end state.
- CI runs lint (ruff) and tests on every push; the container build runs on every push and publishes on tags.

## Deferred

Not in scope until the core is solid: OCR for image-based subtitles, downloading subtitles from external providers, filesystem watching (inotify), notifications, authentication (the tool assumes a trusted home network), and translations (UI is English only).
