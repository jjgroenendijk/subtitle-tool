# Subtitle Tool — Technical Requirements

## 1. Runtime and Deployment

- The application runs as a single Docker container with no required external services.
- The initial target platform is Linux only.
- Both `docker run` and `docker-compose.yml` deployment options must be provided.
- The source repository and container build/publish automation must be hosted on GitHub.
- Official container images must be built and published by GitHub CI.
- GitHub CI must publish official container images to both GitHub-hosted container distribution and Docker Hub.
- The shipped container image must bundle all required processing dependencies; host-installed media-processing dependencies are unsupported.
- PUID and PGID must be configurable through environment variables for host-mounted volume ownership compatibility.
- Container startup behavior must be configurable through environment variables.
- Filesystem watching must be configurable through environment variables.
- When startup-triggered processing is enabled through environment variables, the application must enqueue a fresh processing run on startup.
- Startup-triggered processing must create a new run and must not attempt to resume interrupted in-flight work from a previous process instance.
- Web UI authentication is not required in v1; the tool is assumed to run on a trusted network, and broader exposure is operator-managed.

## 2. Processing State and Configuration Mechanics

- File processing is stateless by default for non-ignored files.
- Persisted configuration must use user-editable JSON or TOML files.
- Reviewed discovery plans must be stored as JSON documents.
- Job history, job detail logs, warnings, and other append-only operational records must be stored as NDJSON logs.
- The application may persist ignore-file contents and log-retention metadata alongside configuration and logs.
- Non-append state-file updates must use an atomic write strategy such as temporary-file replacement on the target filesystem.
- The ignore file acts as a `.gitignore`-style exclusion mechanism for scan discovery.
- Automatic addition of successfully processed items to the ignore file must be user-configurable and enabled by default.
- When automatic ignore-file updates are enabled, the ignore file becomes an explicit persisted processing-state mechanism.
- All settings must be configurable through both the Web UI and Docker environment variables.
- Environment variables act as initial/default values.
- Web UI overrides apply only until the next restart.
- After restart, environment-variable values take precedence again.
- Environment variables must follow a consistent naming convention.
- Configuration validation must reject invalid pipeline combinations before execution.

## 3. Processing Pipeline and Execution Control

- Manual confirmation flows must use separate discovery jobs and execution jobs.
- Discovery jobs must persist the planned actions and skip reasons presented for review.
- Execution jobs must execute against a reviewed plan and must recheck relevant source-file state before destructive actions are performed.
- The execution model must plan around videos and their associated subtitles instead of treating every file in isolation.
- When a video and its subtitles need work, the pipeline order is:
  - Video phase before subtitle phase when extraction or remux work is needed.
  - Encoding normalization before language detection.
  - Language detection before language filtering.
  - SDH/HI flag detection before content cleanup when content-based flag detection is enabled.
  - Format conversion before content cleanup.
  - Content cleanup before sync correction.
  - All content-changing processing before filename normalization.
- Standalone subtitle files may still go through subtitle-only processing, but video-dependent steps must be skipped with a warning.
- Deduplication must be an explicit non-destructive check once all subtitles for the same video are known.
- If a file reaches an uncertain or unsafe decision point at any stage, processing for that file stops for the rest of the current run and a warning is recorded.
- If a reviewed plan no longer matches the current source fingerprint for a planned video or standalone subtitle file, that planned work must be marked invalidated, skipped, and logged; the execution job must not rebuild the plan automatically.
- Only one execution job may run at a time per container.
- While an execution job is active, new triggers must not start concurrent work.
- While an execution job is active, any number of additional triggers must be merged into at most one follow-up run scheduled after the active job completes.
- One worker per container is the default execution model.
- Operators who want parallelism are expected to run multiple containers.
- The application does not coordinate locking across containers; multi-container deployments against the same files are unsupported unless scan paths are separated by the operator.

## 4. Media Integrity and Filesystem Safety

- Subtitle extraction and remuxing must skip work when no relevant embedded subtitle streams are present.
- Remuxing must also skip when the file is already in the desired container and no subtitle extraction is needed.
- AVI files must not be remuxed.
- The system must enforce a container compatibility matrix for remux targets.
- If a target container cannot preserve the required subtitle result safely, the tool must keep a compatible container or skip the unsafe action with a warning; it must not silently drop streams.
- Before remuxing, the tool must verify sufficient disk space for expected output size, required temporary files, and a configurable safety margin.
- Before processing a video file, the tool must verify that file size and modified timestamp remain stable across a configurable stability window.
- If a source file changes while it is being processed, processing for that file must abort and temporary output must be discarded.
- Destructive operations must write temporary output on the target filesystem, validate the result, and only then replace or delete the source.
- The application must not rely on a separate container `tmpfs` working directory for destructive replaceable outputs in v1.
- A separate configurable temporary root for destructive processing outputs is not required in v1.
- Subtitle conversion must use the same temporary-output and validation strategy.
- When a target output path already exists, the system must resolve the collision by appending a predictable suffix rather than overwriting implicitly.
- The same suffixing rules must be applied consistently for remux outputs, converted subtitles, normalized filenames, quarantine outputs, and archive/export outputs.
- If original video files are retained after processing, they must be moved outside scanned paths or excluded from future scans through ignore rules or other explicit exclusions.

## 5. Detection, Matching, and Decision Rules

- Text subtitle language detection must sample subtitle content from the middle of the file while supporting fallback behavior for short files.
- Each language detection result must include a confidence score.
- Files below the configured minimum confidence threshold must not undergo language-dependent destructive actions automatically.
- Low-confidence language conflicts may still be force-renamed if the user explicitly enables that behavior.
- Deduplication must compare all subtitle files associated with the same video, including extracted and pre-existing external subtitles.
- Exact duplicate detection means normalized text and timings match after normalization of encoding and line endings.
- Near-exact duplicate detection means normalized text matches and timings fall within a configurable tolerance.
- Subtitle-to-video association must follow a fixed matching order based on basename matching, normalized similarity, season/episode or movie/year parsing, and parent-folder naming hints.
- If subtitle-to-video association remains ambiguous, the item must be skipped with a warning instead of guessed.

## 6. Sync and Skip Safety

- Sync correction in v1 is audio-based only.
- Image-based subtitles must never be synced automatically.
- If no usable audio track exists, or the sync engine cannot decode the audio track, sync must be skipped and logged with a warning when sync was requested.
- Sync processing must support a per-file timeout.
- When the timeout is exceeded, the tool must skip sync for that file, log the reason, and continue.
- Sync acceptance must be based on explicit quality metrics including pre-sync offset estimate, post-sync alignment/confidence, and a configurable minimum confidence threshold.
- Sync output must be reverted when the sync engine confidence falls below the configured acceptance threshold.
- A separate maximum absolute timing-shift safety limit must block large automatic corrections and convert them into skipped actions with warnings.
- Warnings for skipped actions must preserve the reason, relevant measurements, and the action that was not performed.

## 7. Discovery, Triggering, and Streaming Interfaces

- Scheduled execution must use configurable cron expressions.
- Filesystem watching must use an inotify-based watchdog with configurable debounce behavior.
- Filesystem watching must be enableable and disableable through configuration and environment variables.
- When filesystem watching is enabled, watcher events must trigger execution scoped to the changed files and directly related videos or subtitles.
- Watcher-triggered execution must still begin with a fresh discovery and planning pass for the affected scope rather than executing raw watcher events directly.
- Excluded-from-scan rules must support output directories, quarantine directories, archive/export directories, and ignore-file patterns.
- The control-plane API must use REST endpoints for configuration, job creation, plan review, execution approval, and history retrieval.
- The job detail view must stream live logs over WebSocket.
- Cron-entry editing must provide a human-readable interpretation in the UI.

## 8. Internationalisation Implementation

- The translation system must use community-editable translation files.
- Missing translation keys must fall back to English.
- Date and number formatting must respect the active locale.
- The UI layout must support right-to-left languages.

## 9. Operational Requirements

- Log retention must support configurable maximum age or size with automatic rotation.
- Interrupted jobs must be marked as interrupted and must not be resumed automatically after restart.
- The application is not required to perform startup cleanup or recovery of abandoned temporary processing artifacts in v1.
- CPU and memory resource enforcement are delegated to the container runtime; the application is not required to implement internal resource quotas in v1.
- A health endpoint must be provided for liveness checks.
- A readiness endpoint must be provided for startup/readiness checks.
