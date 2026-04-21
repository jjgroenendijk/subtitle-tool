# Subtitle Tool — Architecture

## Context

The Subtitle Tool is a homelab application that runs alongside a media server and reconciles subtitle and video files toward a configured desired state.

## Architectural Principles

### 1. Desired-State Reconciliation

The system is built around a declarative desired-state model. The user defines the target condition for subtitle and video files, and the application works toward that state instead of executing fixed one-off scripts.

Each run follows the same high-level lifecycle:

1. Scan configured paths and inspect current file state.
2. Match subtitle files to videos when a clear match exists.
3. Diff actual state against the configured desired state.
4. Persist a plan containing proposed actions and skip reasons.
5. Execute only the actions needed to move files toward the desired state.

This model makes repeated runs predictable and minimizes unnecessary work.

### 2. Minimal Persisted State

The tool does not maintain a persistent per-file processing database. Work is derived from the current filesystem state plus a small amount of explicit application state:

- Configuration
- Plans
- Logs
- Ignore rules

This keeps the reconciler simple while still supporting review, auditability, and operational controls.

### 3. Explain-and-Skip Decision Model

The system is designed to automate safe work and skip uncertain actions with a clear explanation.

- Manual runs always expose the plan before execution.
- Automated runs can either execute immediately or wait for confirmation.
- Files that reach an uncertain decision point are skipped instead of being guessed or modified destructively.
- The reason for each skipped action is surfaced through scan results, warnings, and job logs.

### 4. Fail-Isolated Batch Processing

The architecture treats each planned video or standalone subtitle file as independently processable within a batch.

- Failure on one video or subtitle file must not stop the overall job.
- Errors are recorded per video or subtitle file and surfaced in job details.
- Processing stops for that video or subtitle file as soon as the tool reaches an unsafe or uncertain step.

### 5. Simple Single-Container Execution

The application is designed for one container and one execution worker by default.

- Only one execution job runs at a time per container.
- Additional triggers are merged instead of running at the same time.
- Multi-container coordination against the same files is out of scope for v1.

### 6. Source Retention and Loop Prevention

The system supports two retention models:

- Convergent mode: files within scanned paths are expected to end each run in the desired state.
- Archive/export mode: retained originals are allowed only when moved outside scanned paths or excluded from future scans.

This is a core architectural concern because safe retention rules prevent reprocessing loops.

## System Components

The v1 architecture is intentionally small and uses six core components:

- `Scanner`: walks configured roots, applies exclusions, and discovers candidate files.
- `Planner`: matches subtitles to videos, evaluates current state, and produces actions and warnings.
- `Plan Store`: saves discovery output for review and later execution.
- `Executor`: performs planned actions one video or subtitle file at a time using temporary-output safety rules.
- `Job Coordinator`: accepts triggers, enforces single execution, and merges follow-up work.
- `Web App`: provides the REST API, UI, and live WebSocket job-log streaming.

## State Model

The persisted state is limited to four buckets:

- `Configuration`: user-editable JSON or TOML configuration files, plus UI overrides kept in memory until restart.
- `Plans`: persisted discovery results used for manual review and execution auditability.
- `Logs`: append-only NDJSON job history, warnings, and per-job operational events.
- `Ignore rules`: user-authored exclusions plus optional automatically added entries for processed items.

There is no separate persistent file-status database in v1.

## Video and Subtitle Grouping

The planner works directly with videos and subtitles:

- When a subtitle clearly matches a video, the planner treats that video and its subtitles as one planned group.
- When a subtitle does not clearly match a video, it stays as a standalone subtitle file.
- Each planned group or standalone subtitle file carries its own warnings, skip reasons, and planned actions.

If a subtitle file cannot be matched confidently to a video, the tool skips video-dependent work and records a warning instead of guessing.

## Processing Model

When a video needs work, execution uses two simple phases.

### 1. Video Phase

The video phase handles video-originated actions:

- Inspect embedded subtitle streams
- Extract configured subtitle streams when applicable
- Remux the video when required by extraction or container normalization rules

If extraction creates new subtitle files, those files are added to the subtitle work for that same video.

### 2. Subtitle Phase

The subtitle phase handles subtitle-originated actions in dependency order:

1. Encoding normalization
2. Language detection
3. Language filtering
4. SDH/HI flag detection when enabled
5. Format conversion
6. Content cleanup
7. Sync correction
8. Filename normalization

Deduplication is a non-destructive check performed after the tool knows about all subtitles for the same video. It produces warnings and explanations, but it does not delete duplicates automatically in v1.

Standalone subtitle files can still go through subtitle-only processing, but any step that depends on a matched video is skipped with a warning.

Pipeline step toggles must respect these dependencies. Invalid combinations are treated as configuration errors rather than runtime improvisation.

## Plan Model

Each discovery job persists one explicit plan document.

At minimum, the plan contains:

- A plan identifier
- Creation time
- A configuration snapshot
- Planned videos and standalone subtitle files
- For each planned video or standalone subtitle file:
  - Source paths
  - A short summary of the current state
  - Planned actions in execution order
  - Warnings and skip reasons
  - A source fingerprint

The source fingerprint is intentionally small:

- Path
- File size
- Modified time

This keeps review and execution behavior easy to reason about.

## Discovery, Review, and Execution

Manual confirmation flows use separate discovery and execution jobs:

- A discovery job scans files, matches subtitles to videos, produces a plan, and saves the result for review.
- A later execution job consumes that reviewed plan.

Before executing planned work, the executor rechecks the source fingerprint.

- If the fingerprint still matches, execution proceeds.
- If the fingerprint changed, that planned work is marked `invalidated`, skipped, and logged.
- The executor does not try to rebuild the plan during the execution job.

If the user wants a fresh plan for invalidated work, the system requires a new discovery job.

## Trigger Architecture

The system supports four trigger types:

- Manual UI-triggered runs
- Scheduled runs
- Startup-triggered runs when enabled through environment variables
- Filesystem-watch-triggered runs when automatic execution is enabled

All trigger types share the same scan, plan, explain, and execute architecture. The difference is the trigger scope and whether human confirmation is required before execution.

### Job Coordination Rules

The `Job Coordinator` keeps runtime behavior simple:

- Only one execution job may run at a time per container.
- Any number of incoming triggers while an execution job is active are merged into at most one follow-up run.
- Watcher events that arrive while a job is active are merged into the pending watcher scope for that follow-up run.

### Watcher Semantics

The filesystem watcher is optional and is controlled by configuration, including environment variables.

- The user can enable or disable the watcher with an environment variable.
- If the watcher is disabled, filesystem changes do not trigger runs.
- If the watcher is enabled, it debounces file changes and triggers a scoped run for the changed paths.
- A watcher-triggered run still performs fresh discovery and planning for the affected videos and subtitles; it does not execute raw filesystem events directly.

This keeps watcher behavior simple without turning the system into an event-driven workflow engine.

## Path and Retention Rules

The architecture uses a small set of path categories:

- Scanned roots
- Quarantine directory
- Archive/export directory
- Temporary outputs

The following rules apply:

- Quarantine and archive/export directories must live outside scanned roots or be explicitly excluded from future scans.
- Destructive temporary outputs must be written on the target filesystem so validation and replacement stay simple and atomic.
- The v1 architecture does not use a separate container `tmpfs` working directory for replaceable outputs.
- The v1 architecture does not expose a separate configurable temporary root for destructive processing outputs.
- When a target path already exists, the system appends a predictable suffix instead of overwriting implicitly.
- If retained originals would otherwise remain inside scanned roots in a non-desired state, the configuration must rely on archive/export placement or explicit exclusions to prevent reprocessing loops.

## File Discovery Model

The tool uses general file discovery rules rather than a separate media-server-specific mode.

Subtitle-to-video association is based on clear matching signals such as:

- Exact basename matches
- Normalized basename similarity
- Season/episode or movie/year parsing
- Parent-folder naming hints when useful

When those signals do not yield a confident match, the file is skipped instead of guessed, and the reason is recorded in warnings and job logs.

## Extensibility

The architecture leaves room for a few narrow future extension points without introducing a plugin system in v1.

Known deferred extension areas are:

- OCR providers for image-based subtitles
- Subtitle source/provider adapters for third-party downloads
- Notification hooks for failures and skipped-file warnings
