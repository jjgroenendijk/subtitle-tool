# Subtitle Tool — Technical Requirements

## 1. Runtime and Deployment

- The application runs as a single Docker container with no required external services.
- The initial target platform is Linux only.
- Both `docker run` and `docker-compose.yml` deployment options must be provided.
- PUID and PGID must be configurable through environment variables for host-mounted volume ownership compatibility.
- Web UI authentication is not required in v1; the tool is assumed to run on a trusted network, and broader exposure is operator-managed.

## 2. Processing State and Configuration Mechanics

- File processing is stateless by default for non-ignored files.
- The application may persist configuration, job history, job detail logs, ignore-file contents, and log-retention metadata.
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

- The per-file pipeline order is:
  - Encoding normalization before language detection.
  - Subtitle extraction before subtitle processing.
  - Language detection before language filtering.
  - SDH/HI flag detection before content cleanup when content-based flag detection is enabled.
  - Format conversion before content cleanup.
  - Content cleanup before sync correction.
  - All content-changing processing before filename normalization.
- If a file reaches an uncertain or unsafe decision point at any stage, processing for that file stops for the rest of the current run and a warning is recorded.
- Only one execution job may run at a time per container.
- New triggers must be queued or coalesced while another execution job is active.
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
- Subtitle conversion must use the same temporary-output and validation strategy.
- If original video files are retained after processing, they must be moved outside scanned paths or excluded from future scans through ignore rules or other explicit exclusions.

## 5. Detection, Matching, and Decision Rules

- Text subtitle language detection must sample subtitle content from the middle of the file while supporting fallback behavior for short files.
- Each language detection result must include a confidence score.
- Files below the configured minimum confidence threshold must not undergo language-dependent destructive actions automatically.
- Low-confidence language conflicts may still be force-renamed if the user explicitly enables that behavior.
- Deduplication must compare all subtitle files associated with the same media item, including extracted and pre-existing external subtitles.
- Exact duplicate detection means normalized text and timings match after normalization of encoding and line endings.
- Near-exact duplicate detection means normalized text matches and timings fall within a configurable tolerance.
- Subtitle-to-video association must follow a deterministic heuristic order based on basename matching, normalized similarity, season/episode or movie/year parsing, and parent-folder naming hints.
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
- Excluded-from-scan rules must support output directories, quarantine directories, archive/export directories, and ignore-file patterns.
- The job detail view must stream live logs over WebSocket.
- Cron-entry editing must provide a human-readable interpretation in the UI.

## 8. Internationalisation Implementation

- The translation system must use community-editable translation files.
- Missing translation keys must fall back to English.
- Date and number formatting must respect the active locale.
- The UI layout must support right-to-left languages.

## 9. Operational Requirements

- Log retention must support configurable maximum age or size with automatic rotation.
- A health endpoint must be provided for liveness checks.
- A readiness endpoint must be provided for startup/readiness checks.
