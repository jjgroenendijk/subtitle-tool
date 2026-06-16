# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Authoritative reference for the internals of the `subtitle_tool` package. The
root `/AGENTS.md` owns repo-level layout, development commands, bootstrap
settings, and conventions (git, commit format, writing style, backlog) and
points here for package detail. Keep the two non-overlapping.

## Subpackage map

- `config/` - bootstrap env settings (`BootstrapSettings`) and the persisted TOML
  config model plus loader/validation (`load_config`, `save_config` writes the file
  atomically). `languages.py` is the shared catalog of selectable languages (ISO
  639-1 code to name) the config form's language pickers draw on.
- `scanner/` - recursive walker with gitignore-style excludes (`walk.py`),
  subtitle-to-video matching rules (`matching.py`), scan orchestration
  (`scanner.py`), and the inventory result models (`models.py`). Entry point:
  `scan(config)`.
- `pipeline/` - per-file transformations. `runner.py` applies the enabled steps in
  dependency order (entry point `run_pipeline(scan_result, config, dry_run=)`),
  `steps/` holds the steps (`encoding`, `conversion`, `cleanup`, `sync`, `detection`,
  `naming`). The default order runs `sync` before `detection`, but when language
  filtering is enabled the runner detects first so a subtitle the filter deletes never
  pays for the expensive sync alignment; a file the filter marks for deletion skips the
  remaining steps. The reorder is safe because sync only shifts timings, not the
  dialogue the detector reads. `safety.py` is the temp-file-plus-atomic-replace write
  layer, `srt.py` a
  tolerant SRT block model, `workitem.py` the mutable per-file state, and `models.py`
  the action/result reporting types. `run_pipeline` takes an optional `on_file`
  callback for live progress. The video phase runs first per video group: `video.py`
  (`process_video`) extracts embedded text subtitle streams to external SRT and
  optionally remuxes the video to drop them, `ffmpeg.py` wraps the ffprobe/ffmpeg
  subprocess calls, and `langcodes.py` maps ffprobe's ISO 639-2 tags to the ISO 639-1
  codes used in filenames. Extracted files feed back into the per-file steps in the
  same run. The `sync` step corrects out-of-sync video-matched SRT subtitles against
  the video audio via ffsubsync (`sync.py` wraps the subprocess with a per-file
  timeout), gated on offset, score, and shift thresholds.
- `jobs/` - job history and the background worker. `store.py` is the SQLite history
  (`JobStore`: jobs, per-file results, retention pruning, marking jobs left `running`
  by a stopped process as interrupted), `broker.py` the in-memory pub/sub bridging the
  worker thread to SSE subscribers (`EventBroker`), `worker.py` the single-job
  background runner (`Worker.submit`/`Worker.start`, a `ScanRequest` with optional
  directory scope, and trigger collapsing into one queued follow-up via
  `merge_requests`), and `models.py` the `Job`/`JobFile` records. The worker
  reconciles each scan against the media index before processing, so unchanged files
  are skipped and only new/changed paths reach the pipeline; after a real run it
  re-reconciles the directories the pipeline touched (`_refresh_index`, scoped to
  them) so the index reflects renames, deletes, rewrites, and extracted subtitles
  immediately rather than lagging until the next scan.
- `index/` - the SQLite media index (`index.db`). `store.py` is the `IndexStore`: a
  `threading.Lock`-guarded `sqlite3` connection with videos, subtitles, and a subtitle
  change/audit-history table. `reconcile(scan_result, scope=, dry_run=)` fingerprints
  (size, mtime) the inventory against stored rows, returning a `ReconcileResult`
  (new/changed/unchanged/gone, and `process_paths` = new|changed); it loads existing
  rows once, classifies in memory, and writes upserts, history, and in-scope gone
  markings in batched `executemany` passes, so a large scan avoids a query per file (a
  dry run classifies read-only and writes nothing). `library(wanted_languages)`
  returns `LibraryVideo` coverage with per-video missing wanted languages. `models.py`
  holds the records. The index is rebuildable: delete `index.db` and a full scan
  repopulates it.
- `logging.py` - structured JSON logging for container stdout. `configure_logging()`
  installs one stdout handler on the `subtitle_tool` package logger with
  `StructuredFormatter`, which emits one JSON object per line: base fields (timestamp,
  level, logger, event) plus any structured fields a caller passed via `extra`. Modules
  log through `logging.getLogger(__name__)` with the message as the event name. The web
  app factory configures it; the CLI scan report stays on `print`.
- `scheduler.py` - `Scheduler`: a background thread submitting a full scan on the
  configured interval, with optional scan-on-startup. Re-reads the interval each cycle.
- `watcher.py` - `Watcher`: an inotify (watchdog) observer over the media paths
  feeding a `StabilityTracker` that debounces events and queues a directory only once
  its files' size and mtime have been stable for the configured window, then submits a
  scoped scan.
- `web/` - FastAPI app factory (`create_app`) serving the dashboard, job detail,
  library, and configuration pages, an SSE stream (`sse.py`), and a JSON API.
  `health.py` holds the readiness checks behind `/health/ready` (config directory
  access and a `ping()` on each SQLite store), kept separate from the app factory so
  they are unit-testable; `/health/live` is liveness and `/health` a deprecated alias.
  `forms.py` derives the config form from the model, honouring a field's
  `json_schema_extra` `widget` hint (`language` multi-select from the language catalog,
  `path` directory picker) to choose its input; `serialize.py` shapes job and library
  JSON; `templates/` and `static/` hold the server-rendered UI. The library view
  (`/library`, `/api/library`) lists indexed videos with their subtitle languages,
  flags, and missing wanted languages from the media index. `/api/browse` lists a
  container directory's subdirectories for the media-path picker, confined to
  `BootstrapSettings.browse_root`.
- `cli.py` / `__main__.py` - console entry point `subtitle-tool` (`scan`/`serve`),
  `__main__.py` delegates to `cli`.

## How a scan flows through these subpackages

A scan is the spine that ties the subpackages together; trace it before changing
any one piece:

1. `scanner.scan(config)` walks the media paths, matches subtitles to videos, and
   returns an inventory.
2. The worker (`jobs/worker.py`) reconciles that inventory against the media index
   (`index/store.py` `reconcile`) so unchanged files are skipped; only new/changed
   paths (`process_paths`) reach the pipeline.
3. `pipeline.run_pipeline(...)` runs the video phase first per video group, then the
   per-file steps in dependency order. Extracted files feed back into the per-file
   steps in the same run.
4. The worker re-reconciles the touched directories (`_refresh_index`) so renames,
   deletes, rewrites, and extractions land in the index immediately.
5. Progress streams via `run_pipeline`'s `on_file` callback → `jobs/broker.py`
   pub/sub → `web/sse.py` SSE → the dashboard.

Triggers that start this flow: `scheduler.py`, `watcher.py`, web dashboard buttons,
and `cli.py scan`.

## Invariants when editing this package

- All file mutations go through `pipeline/safety.py` (temp file + atomic replace).
  Never write a media/subtitle file in place.
- The pipeline stays idempotent and re-runnable: a second scan over unchanged files
  produces no actions.
- Honor `dry_run` everywhere - a dry run classifies and reports planned actions but
  writes nothing, including the index.
- Filenames are the source of truth for language; the index is a rebuildable cache.
  Keep `pipeline/langcodes.py` and `config/languages.py` consistent (ISO 639-1 in
  filenames).
- `tests/` mirrors this package directory for directory; add tests alongside the
  module they cover.
