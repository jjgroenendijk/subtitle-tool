# Subtitle Tool — Technical Requirements

Implementation constraints that follow from the architecture. Kept deliberately short; anything not
listed here is an implementation detail.

## Runtime and Deployment

- Single Docker container, Linux only, no external services.
- Images are built by GitHub Actions and published to GitHub Container Registry: build on every
  push, publish on tagged releases plus a `latest` tag from the main branch.
- The image bundles ffmpeg/ffprobe and all Python dependencies.
- PUID and PGID are configurable through environment variables so written files match the ownership
  of the Plex media library.
- A `docker-compose.yml` example is provided in the repository.
- The application exposes split health endpoints: `/health/live` (liveness: the process is running)
  and `/health/ready` (readiness: the local state needed to serve real work — config directory
  access and both SQLite databases answering a query — is usable, returning 503 with the failing
  checks otherwise). The legacy `/health` path remains as a deprecated liveness alias for existing
  health checks.

## Observability

- Runtime events (worker job start/finish, per-file pipeline outcomes, subprocess failures) are
  logged to stdout as one JSON object per line so a container log collector can parse and index them
  without a regex. Human-facing CLI scan output stays on plain text.
- Job lifecycle lines carry the job id, trigger, mode, status, elapsed time, and the
  changed/warning/error counts; per-file failure and warning lines carry the file path and the error
  or warnings, so a failing job or file is diagnosable from the logs alone. The log level defaults
  to `INFO` and is set by the `LOG_LEVEL` environment variable.

## State and Configuration

- One configuration file (TOML or YAML) in the `/config` volume holds all settings; the web UI reads
  and writes this file. Writes are atomic (temp file plus rename).
- Configuration is validated on save and on load; invalid step combinations are rejected with a
  clear error.
- Language fields are presented in the web UI as predefined selectable choices drawn from a shared
  language catalog (ISO 639-1 code to readable name); the form maps the catalog to picker options
  while the stored value stays a list of bare codes. The catalog only constrains the UI: a code
  outside it is still accepted on load and through the JSON API, which validate by shape (lowercase
  two-letter ISO 639-1) rather than against the catalog.
- The form metadata is derived from the config model: a field's `json_schema_extra` `widget` hint
  (`language`, `path`) selects its picker, so adding a setting still wires up its input
  automatically.
- Job history, per-file results, and warnings are stored in a SQLite database (`jobs.db`) in
  `/config`. Old jobs are pruned by a configurable retention limit.
- A media index SQLite database (`index.db`) in `/config` records videos and subtitles with: path
  (identity), fingerprint (size and mtime), parsed language and flags, subtitle-to-video match
  status, and first-seen / last-seen / last-changed timestamps.
- Each scan reconciles the filesystem against the index; a file whose fingerprint matches its row is
  skipped. The index is authoritative for deciding what work a scan does, and it is rebuildable from
  a full scan, so deleting `index.db` forces full reprocessing.
- Pipeline steps remain idempotent and every file rewrite stays atomic, so a stale or missing index
  never produces an unsafe action.

## Execution Control

- One background worker runs one job at a time. Triggers arriving during a job collapse into at most
  one queued follow-up run.
- Long-running operations (ffmpeg extraction, remux, sync) run in the worker and must not block the
  web UI.
- Every external media subprocess (ffprobe, ffmpeg, ffsubsync) runs under a bounded timeout so a
  corrupt or stalled file cannot wedge the single worker; a timeout is reported as a per-file
  warning and the job continues. Read-only ffprobe inspections (subtitle streams, audio-stream
  presence) are cached per run, so a video matched by several subtitles is probed once rather than
  once per subtitle.
- A failure on one file is recorded and the job continues with the next file.
- Jobs interrupted by a restart are marked interrupted and not resumed; the next scheduled scan
  covers the work because steps are idempotent.
- The running job can be stopped on request from the web UI. Cancellation is cooperative: the worker
  observes the stop signal only at a safe boundary between files (and before each video phase),
  never mid-transformation or mid atomic-replace, so no partial or half-written file is left behind.
  A stopped job is recorded with a distinct `cancelled` status (separate from `interrupted`, which
  is a crash/restart) and a finish timestamp, and the files already processed remain recorded; the
  rest are left for the next scan, which is safe because the steps are idempotent. Long-running
  per-file subprocesses (ffmpeg extraction, remux, ffsubsync) run to their existing per-file timeout
  before the next boundary check, so a stop takes effect once the current file completes rather than
  killing a subprocess mid-write. Stopping is deliberate, so any queued follow-up run is dropped and
  the worker returns to idle.

## Filesystem Safety

- Every file rewrite goes through a temporary file on the same filesystem, validation of the result,
  then an atomic replace.
- Before remuxing, verify sufficient free disk space for the expected output.
- Skip a video whose size or mtime changed during processing and discard temporary output.
- AVI files are not remuxed.
- When a target path already exists, append a predictable numeric suffix instead of overwriting.
- Deleting source files (video after remux, subtitle after conversion, filtered languages) is opt-in
  per setting and off by default.

## Detection and Matching Rules

- Subtitle-to-video matching tries, in order: exact basename match, normalized basename similarity,
  season/episode or movie/year parsing. Anything still ambiguous is skipped with a warning.
- The set of wanted subtitle languages is configurable, and the media index reports, per video,
  which wanted languages have no matching subtitle.
- Language detection samples from the middle of the file, falls back gracefully for short files, and
  always yields a confidence score.
- Actions gated on language (filtering, renaming) require the configured minimum confidence.
- Sync corrections require a measured offset above a minimum threshold, an alignment score above an
  acceptance threshold, and an absolute shift below a safety cap; otherwise the original timings are
  kept and a warning recorded. ffsubsync runs as a subprocess under a per-file timeout so a slow
  alignment cannot wedge the worker, and a video with no audio track is skipped with a warning.

## Interfaces

- Scheduling uses a simple configurable interval (hours) plus an optional scan-on-startup flag; cron
  expressions are not in scope.
- Filesystem watching uses inotify (via the watchdog library) on the media paths, enabled by default
  and toggleable in the configuration.
- Watcher events are debounced, and a new or changed file is only queued once its size and mtime
  have been stable for a configurable window, so files still being copied or downloaded are never
  processed.
- A watcher trigger queues a scan scoped to the changed directories through the normal worker queue;
  it goes through full discovery and pipeline logic and is subject to the same one-job-at-a-time and
  trigger-collapsing rules as any other trigger.
- The web UI uses server-rendered pages with a small JSON API underneath; job progress and live job
  events are pushed over Server-Sent Events, with the JSON API as the fallback for initial page
  state.
- Page-local interactivity (the config language picker filter and selected count, the config
  directory picker's selected-path list and browse state, the library "show gaps only" toggle) uses
  Alpine.js as a thin local-interaction layer. The server-rendered Jinja templates and FastAPI
  routes remain the source of truth; Alpine only manages transient in-page state through named
  `Alpine.data(...)` components registered in `app.js`. There is no frontend bundler or build step.
- Alpine.js is loaded from a local static asset pinned to a concrete version (the `@alpinejs/csp`
  CSP build vendored at `src/subtitle_tool/web/static/vendor/alpine.csp.min.js`), never a CDN. The
  CSP build forbids inline expression evaluation, so template expressions stay limited to property
  and method references while the logic lives in the components. Elements that Alpine manages carry
  `x-cloak` so they do not flash uninitialized state.
- Alpine.js is tracked for version and security updates by Dependabot through the npm ecosystem: a
  minimal `frontend/package.json` plus `frontend/package-lock.json` pin the package, and
  `npm ci && npm run vendor` (run from `frontend/`) refreshes the committed static asset from the
  pinned package. That npm manifest is dependency-tracking and vendor-refresh tooling only; it is
  never a runtime or application build step, and the container ships the committed asset.
- Media paths are chosen with a server-side directory browser: a JSON endpoint lists the
  subdirectories of a container path, and the config page enhances the media-path field into a
  picker over that endpoint. Browsing is confined to a configurable root (`BROWSE_ROOT`, default the
  container root `/`) and rejects any path resolving outside it, so the picker only offers paths the
  scanner can use from inside the container. A plain browser file input is deliberately not used
  because it would expose client-side paths the container cannot see.
- The UI is English only.
- The page layout is responsive: a sticky left-side navigation rail on desktop-width viewports,
  collapsing to a sticky top bar below a narrow breakpoint so the menu stays visible and usable on
  mobile screens. Main content fills the width beside the rail rather than being capped and centred.
  The active route is marked with an `active` class and `aria-current="page"`, derived server-side
  from the page's template block so the current link is highlighted without client state.
- The visual design is a translucent, layered interface: translucent layered surfaces
  (`backdrop-filter` blur over a fixed gradient backdrop), depth via soft shadows, and a light/dark
  palette switched by `prefers-color-scheme` through CSS custom properties. The direction is adapted
  to sharp edges (square corners, `border-radius: 0`) so controls read as crisp rather than rounded.
  Colors, translucent surface fills, borders, blur, and shadows are declared once as CSS custom
  properties and referenced throughout. The styles are a small, ordered set of plain CSS files under
  `web/static/css/` (`tokens.css`, then `base.css`, `components.css`, `forms.css`, `tables.css`),
  loaded directly by the browser through explicit `<link>` tags in `base.html` in that dependency
  order (no `@import`, so loading and debugging stay straightforward). Tokens load first so the
  later files can reference them; shared visual values live in `tokens.css` as custom properties
  rather than being duplicated. No CSS framework, preprocessor, bundler, or build step is
  introduced. The full visual direction, including the requirement to extend token coverage to
  radii, spacing, z-index layers, and motion timings, is specified in `design-requirements.md`.
- Project-owned CSS is linted with Stylelint, run through a single pinned `npx` command against the
  `web/static/css/` files only (vendored assets such as `static/vendor/alpine.csp.min.js` are
  excluded). The config lives at `tools/stylelint.config.cjs`; Stylelint is not added to
  `package.json`. CSS linting is local git-hook enforcement only (the `scripts/pre-commit/40-css.sh`
  and `scripts/pre-push/40-css.sh` hooks), not a CI step.
- The library is a data table: cells do not wrap (`white-space: nowrap`) and the table sits in a
  horizontally scrollable container so wide values never force the whole page sideways. Sortable
  column headers are plain links carrying `sort` and `dir` query parameters; the server sorts the
  full in-memory library list before paginating, so the order is consistent across pages, and the
  active header exposes `aria-sort`. Sorting needs no JavaScript.
- The configuration page exposes a maintenance action that clears the media index. It posts to a
  dedicated server route (`POST /config/reset-index`) guarded by a client-side confirmation, and the
  handler empties the index tables in place via `IndexStore.reset()` (rather than unlinking the file
  under the live connection); reconcile then sees no rows and the next scan reprocesses everything.
  The config file and media files are untouched.
- The configuration language pickers lay their checkbox options out in a CSS grid that flows into as
  many columns as fit the field width and grows downward, so a long catalogue scrolls vertically and
  never horizontally.

## Code Organization

- Separation of concerns is a standing implementation standard, not a one-off cleanup. Each module
  keeps to one job; favour small, focused, independently testable units over modules that accumulate
  a second responsibility.
- Shared domain logic lives in a neutral module rather than inside a feature package that is merely
  its first caller. Subtitle-filename parsing (video basename, language, flags) is a neutral
  top-level module used by the scanner, index, and pipeline, so no single caller owns it; logic
  imported across packages belongs in a neutral home.
- Orchestration modules orchestrate and delegate presentation, reporting, and payload shaping to
  focused helpers. The background job worker drives the run and hands counters, result-to-store
  mapping, and SSE payload shaping to a separate reporting helper. The web app factory is a
  composition root (lifecycle wiring and route handlers) with page/API logic — library-table sorting
  and pagination, directory browsing, readiness checks — extracted into helpers that are
  unit-testable without the application.
- A helper that carries logic gets its own unit tests, not only coverage through its caller. When a
  module grows a second responsibility, extract the new boundary and record it in the package map.

## Testing and CI

- pytest unit tests for each pipeline step using fixture subtitle files.
- Scanner and matcher tests against temporary directory trees.
- One end-to-end test: full scan of a fixture library in dry-run and real mode, asserting the
  resulting filesystem state.
- GitHub Actions runs `lint.yml` (ruff plus Markdown format/lint) and `test.yml` (pytest with the
  coverage gate) as independent parallel workflows that share setup through the
  `.github/actions/setup-env` composite action; merges require green CI. Pull requests run the full
  set; pushes run only on `main` and version tags. Concurrency groups cancel superseded PR runs but
  never cancel `main` or tag runs.
