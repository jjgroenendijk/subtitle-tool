# Subtitle Tool — Technical Requirements

Implementation constraints that follow from the architecture. Kept deliberately short; anything not listed here is an implementation detail.

## Runtime and Deployment

- Single Docker container, Linux only, no external services.
- Images are built by GitHub Actions and published to GitHub Container Registry: build on every push, publish on tagged releases plus a `latest` tag from the main branch.
- The image bundles ffmpeg/ffprobe and all Python dependencies.
- PUID and PGID are configurable through environment variables so written files match the ownership of the Plex media library.
- A `docker-compose.yml` example is provided in the repository.
- The application exposes a health endpoint for liveness checks.

## State and Configuration

- One configuration file (TOML or YAML) in the `/config` volume holds all settings; the web UI reads and writes this file. Writes are atomic (temp file plus rename).
- Configuration is validated on save and on load; invalid step combinations are rejected with a clear error.
- Job history, per-file results, and warnings are stored in a SQLite database in `/config`. Old jobs are pruned by a configurable retention limit.
- No per-file processing database: pipeline steps are idempotent, so the filesystem is the source of truth.

## Execution Control

- One background worker runs one job at a time. Triggers arriving during a job collapse into at most one queued follow-up run.
- Long-running operations (ffmpeg extraction, remux, sync) run in the worker and must not block the web UI.
- A failure on one file is recorded and the job continues with the next file.
- Jobs interrupted by a restart are marked interrupted and not resumed; the next scheduled scan covers the work because steps are idempotent.

## Filesystem Safety

- Every file rewrite goes through a temporary file on the same filesystem, validation of the result, then an atomic replace.
- Before remuxing, verify sufficient free disk space for the expected output.
- Skip a video whose size or mtime changed during processing and discard temporary output.
- AVI files are not remuxed.
- When a target path already exists, append a predictable numeric suffix instead of overwriting.
- Deleting source files (video after remux, subtitle after conversion, filtered languages) is opt-in per setting and off by default.

## Detection and Matching Rules

- Subtitle-to-video matching tries, in order: exact basename match, normalized basename similarity, season/episode or movie/year parsing. Anything still ambiguous is skipped with a warning.
- Language detection samples from the middle of the file, falls back gracefully for short files, and always yields a confidence score.
- Actions gated on language (filtering, renaming) require the configured minimum confidence.
- Sync corrections (when implemented) require a measured offset above a minimum threshold, a result confidence above an acceptance threshold, and an absolute shift below a safety cap; otherwise the result is reverted and a warning recorded.

## Interfaces

- Scheduling uses a simple configurable interval (hours) plus an optional scan-on-startup flag; cron expressions are not in scope.
- Filesystem watching uses inotify (via the watchdog library) on the media paths, enabled by default and toggleable in the configuration.
- Watcher events are debounced, and a new or changed file is only queued once its size and mtime have been stable for a configurable window, so files still being copied or downloaded are never processed.
- A watcher trigger queues a scan scoped to the changed directories through the normal worker queue; it goes through full discovery and pipeline logic and is subject to the same one-job-at-a-time and trigger-collapsing rules as any other trigger.
- The web UI uses server-rendered pages with a small JSON API underneath; job progress and live job events are pushed over Server-Sent Events, with the JSON API as the fallback for initial page state.
- The UI is English only.

## Testing and CI

- pytest unit tests for each pipeline step using fixture subtitle files.
- Scanner and matcher tests against temporary directory trees.
- One end-to-end test: full scan of a fixture library in dry-run and real mode, asserting the resulting filesystem state.
- GitHub Actions runs ruff and pytest on every push; merges require green CI.
