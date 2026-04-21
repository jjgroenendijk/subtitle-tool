# Subtitle Tool — Architecture

## Context

The Subtitle Tool is a homelab application that runs alongside a media server and reconciles subtitle and video files toward a configured desired state.

## Architectural Principles

### 1. Desired-State Reconciliation

The system is built around a declarative desired-state model. The user defines the target condition for subtitle and video files, and the application continuously works toward that state instead of executing fixed one-off scripts.

Each run follows the same high-level lifecycle:

1. Scan configured paths and inspect current file state.
2. Diff actual state against the configured desired state.
3. Present planned actions and any skip reasons when human confirmation is required.
4. Execute only the actions needed to move files toward the desired state.

This model makes repeated runs predictable and minimizes unnecessary work.

### 2. Stateless by Default, With Optional Persisted Exclusions

File processing is stateless by default. A new run determines work from the current filesystem state instead of relying on historical per-file processing records.

The one explicit exception is the optional ignore-file mechanism:

- The tool may maintain a `.gitignore`-style exclusion file.
- The user can enable automatic addition of processed items to that file.
- When enabled, that ignore file becomes an intentional persisted processing-state mechanism for future scan exclusion.

Application state is otherwise limited to operational concerns such as configuration, logs, and job history.

### 3. Explain-and-Skip Decision Model

The system is designed to automate safe work and skip uncertain actions with a clear explanation.

- Manual runs always expose planned actions before execution.
- Automated runs can either execute immediately or wait for confirmation.
- Files that reach an uncertain decision point are skipped instead of being guessed or modified destructively.
- The reason for each skipped action is surfaced through scan results, warnings, and job logs.

### 4. Fail-Isolated Batch Processing

The architecture treats files as independently processable units within a batch.

- Failure on one file must not stop the overall job.
- Errors are recorded per file and surfaced in job details.
- Files with uncertain or unsafe actions stop at the point of uncertainty and do not continue through later pipeline stages in that run.

### 5. Source Retention Model

The system supports two retention models:

- Convergent mode: files within scanned paths are expected to end each run in the desired state.
- Archive/export mode: retained originals are allowed only when moved outside scanned paths or excluded from future scans.

This retention model is a core architectural concern because it defines how the system avoids reprocessing loops.

## Processing Pipeline

When multiple actions are required for one file, the processing pipeline follows a fixed dependency order:

1. Encoding normalization
2. Subtitle extraction
3. Language detection
4. SDH/HI flag detection when enabled
5. Format conversion
6. Content cleanup
7. Sync correction
8. Filename normalization

Pipeline step toggles must respect these dependencies. Invalid combinations are treated as configuration errors rather than runtime improvisation.

## Trigger Architecture

The system supports three trigger types:

- Manual UI-triggered runs
- Scheduled runs
- Filesystem-watch-triggered runs

All trigger types share the same scan, diff, explain, and execute architecture. The difference is only when human confirmation is required before execution.

## File Discovery Model

The tool uses generic file-discovery heuristics rather than a separate media-server-specific mode.

Subtitle-to-video association is based on deterministic matching signals such as:

- Exact basename matches
- Normalized basename similarity
- Season/episode or movie/year parsing
- Parent-folder naming hints when useful

When those signals do not yield a confident match, the file is skipped instead of guessed, and the reason is recorded in warnings and job logs.

## Extensibility

The architecture should leave room for future extension points without requiring a redesign of the core processing model. Known deferred extension areas are:

- OCR for image-based subtitles
- Subtitle downloading from third-party providers
- Notification hooks for failures and skipped-file warnings
