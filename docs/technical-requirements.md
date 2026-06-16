# Subtitle Tool — Technical Requirements

Implementation constraints that follow from the architecture. Kept deliberately short; anything not listed here is an implementation detail.

## Runtime and Deployment

- Single Docker container, Linux only, no external services.
- Images are built by GitHub Actions and published to GitHub Container Registry: build on every push, publish on tagged releases plus a `latest` tag from the main branch.
- The image bundles ffmpeg/ffprobe and all Python dependencies.
- PUID and PGID are configurable through environment variables so written files match the ownership of the Plex media library.
- A `docker-compose.yml` example is provided in the repository.
- The application exposes split health endpoints: `/health/live` (liveness: the
  process is running) and `/health/ready` (readiness: the local state needed to
  serve real work — config directory access and both SQLite databases answering a
  query — is usable, returning 503 with the failing checks otherwise). The legacy
  `/health` path remains as a deprecated liveness alias for existing health checks.

## Observability

- Runtime events (worker job start/finish, per-file pipeline outcomes, subprocess
  failures) are logged to stdout as one JSON object per line so a container log
  collector can parse and index them without a regex. Human-facing CLI scan output
  stays on plain text.
- Job lifecycle lines carry the job id, trigger, mode, status, elapsed time, and the
  changed/warning/error counts; per-file failure and warning lines carry the file
  path and the error or warnings, so a failing job or file is diagnosable from the
  logs alone. The log level defaults to `INFO` and is set by the `LOG_LEVEL`
  environment variable.

## State and Configuration

- One configuration file (TOML or YAML) in the `/config` volume holds all settings; the web UI reads and writes this file. Writes are atomic (temp file plus rename).
- Configuration is validated on save and on load; invalid step combinations are rejected with a clear error.
- Language fields are presented in the web UI as predefined selectable choices drawn from a shared language catalog (ISO 639-1 code to readable name); the form maps the catalog to picker options while the stored value stays a list of bare codes. The catalog only constrains the UI: a code outside it is still accepted on load and through the JSON API, which validate by shape (lowercase two-letter ISO 639-1) rather than against the catalog.
- The form metadata is derived from the config model: a field's `json_schema_extra` `widget` hint (`language`, `path`) selects its picker, so adding a setting still wires up its input automatically.
- Job history, per-file results, and warnings are stored in a SQLite database (`jobs.db`) in `/config`. Old jobs are pruned by a configurable retention limit.
- A media index SQLite database (`index.db`) in `/config` records videos and subtitles with: path (identity), fingerprint (size and mtime), parsed language and flags, subtitle-to-video match status, and first-seen / last-seen / last-changed timestamps.
- Each scan reconciles the filesystem against the index; a file whose fingerprint matches its row is skipped. The index is authoritative for deciding what work a scan does, and it is rebuildable from a full scan, so deleting `index.db` forces full reprocessing.
- Pipeline steps remain idempotent and every file rewrite stays atomic, so a stale or missing index never produces an unsafe action.

## Execution Control

- One background worker runs one job at a time. Triggers arriving during a job collapse into at most one queued follow-up run.
- Long-running operations (ffmpeg extraction, remux, sync) run in the worker and must not block the web UI.
- Every external media subprocess (ffprobe, ffmpeg, ffsubsync) runs under a bounded timeout so a corrupt or stalled file cannot wedge the single worker; a timeout is reported as a per-file warning and the job continues. Read-only ffprobe inspections (subtitle streams, audio-stream presence) are cached per run, so a video matched by several subtitles is probed once rather than once per subtitle.
- A failure on one file is recorded and the job continues with the next file.
- Jobs interrupted by a restart are marked interrupted and not resumed; the next scheduled scan covers the work because steps are idempotent.
- The running job can be stopped on request from the web UI. Cancellation is cooperative: the worker observes the stop signal only at a safe boundary between files (and before each video phase), never mid-transformation or mid atomic-replace, so no partial or half-written file is left behind. A stopped job is recorded with a distinct `cancelled` status (separate from `interrupted`, which is a crash/restart) and a finish timestamp, and the files already processed remain recorded; the rest are left for the next scan, which is safe because the steps are idempotent. Long-running per-file subprocesses (ffmpeg extraction, remux, ffsubsync) run to their existing per-file timeout before the next boundary check, so a stop takes effect once the current file completes rather than killing a subprocess mid-write. Stopping is deliberate, so any queued follow-up run is dropped and the worker returns to idle.

## Filesystem Safety

- Every file rewrite goes through a temporary file on the same filesystem, validation of the result, then an atomic replace.
- Before remuxing, verify sufficient free disk space for the expected output.
- Skip a video whose size or mtime changed during processing and discard temporary output.
- AVI files are not remuxed.
- When a target path already exists, append a predictable numeric suffix instead of overwriting.
- Deleting source files (video after remux, subtitle after conversion, filtered languages) is opt-in per setting and off by default.

## Detection and Matching Rules

- Subtitle-to-video matching tries, in order: exact basename match, normalized basename similarity, season/episode or movie/year parsing. Anything still ambiguous is skipped with a warning.
- The set of wanted subtitle languages is configurable, and the media index reports, per video, which wanted languages have no matching subtitle.
- Language detection samples from the middle of the file, falls back gracefully for short files, and always yields a confidence score.
- Actions gated on language (filtering, renaming) require the configured minimum confidence.
- Sync corrections require a measured offset above a minimum threshold, an alignment score above an acceptance threshold, and an absolute shift below a safety cap; otherwise the original timings are kept and a warning recorded. ffsubsync runs as a subprocess under a per-file timeout so a slow alignment cannot wedge the worker, and a video with no audio track is skipped with a warning.

## Interfaces

- Scheduling uses a simple configurable interval (hours) plus an optional scan-on-startup flag; cron expressions are not in scope.
- Filesystem watching uses inotify (via the watchdog library) on the media paths, enabled by default and toggleable in the configuration.
- Watcher events are debounced, and a new or changed file is only queued once its size and mtime have been stable for a configurable window, so files still being copied or downloaded are never processed.
- A watcher trigger queues a scan scoped to the changed directories through the normal worker queue; it goes through full discovery and pipeline logic and is subject to the same one-job-at-a-time and trigger-collapsing rules as any other trigger.
- The web UI uses server-rendered pages with a small JSON API underneath; job progress and live job events are pushed over Server-Sent Events, with the JSON API as the fallback for initial page state.
- Media paths are chosen with a server-side directory browser: a JSON endpoint lists the subdirectories of a container path, and the config page enhances the media-path field into a picker over that endpoint. Browsing is confined to a configurable root (`BROWSE_ROOT`, default the container root `/`) and rejects any path resolving outside it, so the picker only offers paths the scanner can use from inside the container. A plain browser file input is deliberately not used because it would expose client-side paths the container cannot see.
- The UI is English only.
- The page layout is responsive: a sticky left-side navigation rail on desktop-width viewports, collapsing to a sticky top bar below a narrow breakpoint so the menu stays visible and usable on mobile screens.

## Testing and CI

- pytest unit tests for each pipeline step using fixture subtitle files.
- Scanner and matcher tests against temporary directory trees.
- One end-to-end test: full scan of a fixture library in dry-run and real mode, asserting the resulting filesystem state.
- GitHub Actions runs ruff and pytest on every push; merges require green CI.
