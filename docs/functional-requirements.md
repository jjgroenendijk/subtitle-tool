# Subtitle Tool — Functional Requirements

## Context

Homelab subtitle cleanup tool running as a Docker container alongside a media server (Plex). The goal is to enforce a clean, standardised subtitle state across a media library: external subs only, correct language tags, proper format, synced timing, and clean content.

---

## Processing Model

### Declarative / Desired-State Model

The user configures a **desired state** — the target condition for all subtitle and video files (e.g. "all subs in SRT, UTF-8, English and Dutch only, no embedded subs"). The tool works toward that state:

1. **Scan**: analyse all files in configured paths. Determine current state of each file (format, encoding, language, embedded subs, flags, timing, content issues).
2. **Diff**: compare each file's current state against the desired state configuration. Produce a per-file action list (e.g. "convert ASS→SRT, rename to add language code, strip styling").
3. **Review** (manual trigger only): display scan results and planned actions in the UI. User can inspect per-file details before triggering execution.
4. **Execute**: carry out only the actions needed to reach the desired state. Files already matching the desired state are skipped.

### Stateless Processing with Local App State

- File processing is stateless: each run scans and evaluates files from scratch instead of relying on persisted per-file processing history.
- Idempotency is achieved by comparing current state to desired state — not by remembering past runs.
- The application may persist local app state for operational/UI needs only:
  - User configuration
  - Job history and job detail logs
  - Review queue items and their resolutions
  - Log retention metadata
- Persisted app state must not be required to determine whether a file needs processing on a new run.

### Trigger Behaviour

- **Manual trigger (UI)**: scan → show results and planned actions → user reviews → user triggers execution
- **Cron / Watchdog**: configurable per trigger — either scan → execute immediately (default), or scan → wait for user confirmation in UI
- All execution results are logged and visible in the job detail view regardless of trigger type

### Error Handling

- If a file fails to process (corrupt, ffmpeg crash, disk full, etc.), log the error, skip the file, and continue with the rest of the batch.
- Failed files are visible in the job detail view with error details.

### Operation Dependencies

When multiple actions are needed for a single file, they execute in dependency order:

- Encoding normalisation → before language detection (correct encoding needed for accurate detection)
- Subtitle extraction → before any subtitle processing (subs must be external first)
- Language detection → before language filtering (must know the language to filter)
- SDH/HI flag detection → before content cleanup when auto-detection from subtitle content is enabled
- Format conversion → before content cleanup (cleanup rules are format-specific)
- Content cleanup → before sync correction (clean content improves sync accuracy)
- All processing → before filename normalisation (final name reflects final state)
- Pipeline step toggles must respect these dependencies. Invalid combinations are blocked in the UI and rejected in config validation.
- When a file is flagged for review in one step, the tool may continue with clearly safe, non-dependent actions, but must not perform destructive or dependency-blocked actions beyond that point.

---

## Functional Requirements

### 1. Subtitle Extraction

- Extract embedded text-based subtitle streams (SRT, ASS, SSA) from video files to external files
- Extract embedded image-based subtitle streams (PGS, VOBSUB) to external files
- **Configurable per format**: user selects which embedded subtitle formats to extract (e.g. extract SRT/ASS but leave PGS embedded)
- Remux the video file after extraction to remove extracted subtitle streams
- **Pre-check**: if the video has no embedded subtitle streams (or none matching the configured formats), skip extraction and remux entirely
- Remux output format is configurable: keep original extension (default), MKV, or MP4
- **Pre-check**: if the video is already in the desired container format and has no subs to extract, skip remux
- AVI files are not remuxed (AVI has no subtitle stream support)
- **Delete source toggle (video)**: after extraction + remux, delete original video file. Default: OFF (keep both)
- **Disk space check**: before remuxing, verify sufficient disk space is available for the output file. Skip and log a warning if insufficient.
- **File stability check**: before processing a video file, verify the file size is stable (not still being written). Configurable stability window (default: 10 seconds).
- **Mode for retained sources**: if original video files are kept after extraction/remux, the tool must support an explicit archive/export mode that stores retained originals outside scanned paths or otherwise excludes them from future scans.

### 2. Encoding Normalisation

- Detect character encoding of all text-based subtitle files
- Convert all non-UTF-8 files to UTF-8
- Must run before language detection for accurate results

### 3. Format Handling

- Convert ASS, SSA, and optionally VTT subtitle files to SRT
- Formats not in a configurable allowed-formats list are converted if possible, otherwise flagged for review
- Default allowed format: SRT
- PGS and VOBSUB: keep or delete based on language metadata. No OCR conversion (architecture designed for future custom OCR plugin)
- **Delete source toggle (subtitle)**: after conversion, delete original subtitle file. Default: OFF (keep both)

### 4. Language Detection

- Detect the language of each text-based subtitle file
- Sample subtitle blocks from the middle of the file, skipping a configurable number from the start and end (to avoid credits/recaps)
- Assign a confidence score to each detection
- Files below a configurable minimum confidence threshold are flagged for review and must not undergo language-dependent destructive actions
- **Multi-language subs**: detect dominant language, tag with that
- When a language code already exists in the filename but disagrees with detection: behaviour is configurable (rename, keep original, or flag for review)

### 5. Language Filtering

- User configures either a **whitelist** (only these languages kept) or a **blacklist** (these languages removed), not both
  - Whitelist mode: only subtitle files matching listed languages are kept
  - Blacklist mode: subtitle files matching listed languages are acted on, all others kept
  - Empty list = no filtering (all languages kept)
- **Action for filtered languages** is configurable:
  - Delete the subtitle file
  - Move to a configurable quarantine directory (separate from the output directory used for non-overwritten files)
  - Flag in review queue (no action taken)
- Configurable behaviour for subs whose language could not be detected: keep, delete, or flag for review
- Image-based subs with no metadata language tag: keep, delete, or flag for review (configurable)

### 6. Content Cleanup

- **Ad/watermark removal**: remove known patterns ("Subtitles by...", "OpenSubtitles.org", site URLs, etc.)
- **Empty/broken block removal**: strip empty blocks, whitespace-only blocks, duplicate consecutive blocks
- **HI annotation removal** (optional, configurable): strip `[music]`, `(door slams)` etc. from non-SDH subtitle files
- **Artifact cleanup**: remove lone music note characters, leading/trailing punctuation artifacts
- **SRT styling**: configurable per tag type — user can choose to keep or strip each of:
  - Italic tags (`<i>`)
  - Bold tags (`<b>`)
  - Color codes
  - Positioning/alignment tags
  - Default: strip all (produce plaintext SRT)
- All cleanup rules are configurable (enable/disable per rule type)

### 7. Filename Normalisation

- Rename subtitle files to include a standardised language code as the second-to-last dot-segment
  - Prefer ISO 639-1 two-letter codes when available
  - Fall back to ISO 639-2/3 when the detected/configured language has no ISO 639-1 code
  - Example: `Movie.2020.srt` → `Movie.2020.en.srt`
- **Flag normalisation**: standardise HI/SDH/forced flags to canonical forms
  - Configurable mapping (e.g. `.hi` / `.cc` → `.sdh`)
  - Auto-detect flags from subtitle content (e.g. `[music]`, `(door slams)` markers → tag as SDH)
  - **SDH detection threshold**: configurable by user (percentage of blocks containing annotations). Default: 5%
- Existing non-flag segments preserved
- If language cannot be determined confidently, filename normalisation must preserve the existing language segment or leave it absent; it must not invent a language code.

### 8. Deduplication

- After extraction, compare external subs with newly extracted ones
- Detect exact and near-exact duplicate subtitle files
- **Flag duplicates in UI** for user decision — do not auto-delete

### 9. Sync Correction

- **Audio-based sync only**: sync subtitle against the video's audio track
- Detect whether a subtitle is out of sync before attempting correction
- Skip sync if measured median offset is below configurable threshold (default: 500ms)
- Measure sync success using explicit quality metrics:
  - Pre-sync offset estimate
  - Post-sync alignment score/confidence from the sync engine
  - Configurable minimum confidence threshold for accepting the result
- Revert sync output if the sync engine confidence is below the configured threshold
- Maximum allowed absolute timing shift is a separate safety guard; if the proposed shift exceeds a configurable limit (default: 30s), do not apply it automatically and flag for review
- Low-confidence sync results flagged for review
- Only text-based formats are synced; image-based never synced

### 10. Trigger Mechanisms

- **Scheduled scan**: configurable cron expression (default: 2:00 AM daily)
- **Filesystem watchdog**: inotify-based, process new/changed files automatically. Configurable debounce (default: 30 seconds). File stability check before processing (see section 1).
- **Manual trigger from UI**: full library scan or single file reprocess
- Behaviour per trigger type (see Processing Model):
  - Manual: scan → show results → user reviews → user triggers execution
  - Cron/Watchdog: configurable — scan → execute immediately (default), or scan → wait for confirmation

### 11. File Discovery

- User configures one or more root media paths
- **Recursive scan mode** (default): scan all video + subtitle files recursively. Works with any folder structure.
- In recursive scan mode, subtitle-to-video association uses a deterministic heuristic in this order:
  - Exact basename match in the same directory
  - Normalised basename similarity in the same directory
  - Parsed season/episode or movie-year match
  - If multiple candidates remain or confidence is too low, flag for review instead of guessing
- **Plex-aware mode** (optional): use Plex naming conventions (`Movie (Year)/Movie (Year).mkv`) to infer metadata and group related files
- Both modes can be active simultaneously on different paths
- Output directories, quarantine directories, and archive/export directories must be configurable as excluded-from-scan paths to prevent the tool from reprocessing its own outputs or retained originals.

### 12. Web UI

- **Dashboard**: active job progress, stats, recent job history
- **Scan results view**: per-file current state vs. desired state, with planned action list. Shown after manual scan trigger; also accessible for completed cron/watchdog runs.
- **Library browser**: searchable/filterable list of all media files with subtitle status
- **Review queue**: items flagged for manual decision (low-confidence detection, duplicates, ambiguous sync)
- **Configuration page**: all settings editable from UI, grouped by desired state categories
- **Job detail view**: live log streaming, per-action status, errors for failed files
- **Cron field**: shows human-readable translation of cron expression in real-time

### 13. Configuration

- Two "delete source" toggles:
  - Delete original video after extraction + remux (default: OFF)
  - Delete original subtitle after conversion (default: OFF)
- Output location when not deleting source: configurable (same directory with different name, OR custom output directory)
- **Source retention mode**:
  - **Convergent mode**: default. Files inside scanned paths must be brought into the configured desired state by the end of execution.
  - **Archive/export mode**: retained source files are allowed only if they are moved/written outside scanned paths, or otherwise excluded from future scans.
- Quarantine directory (for language filtering): configurable, separate from the output directory
- All pipeline steps individually configurable (enable/disable per step)
- Config validation must enforce pipeline dependencies and reject invalid step combinations
- Config changes take effect on next run (no restart required)
- **Dual configuration sources**: all settings configurable via both the Web UI and Docker environment variables
  - Environment variables serve as initial/default values
  - Web UI changes override environment variable defaults
  - Environment variables use a consistent naming convention (e.g. `SUBTITLE_TOOL_LANG_MODE=whitelist`)

### 14. Review Queue

- Items enter the queue only when the tool cannot make a confident decision:
  - Low-confidence language detection
  - Ambiguous sync results
  - Detected duplicates
  - Formats that can't be converted
- Review items must preserve the scan findings and proposed actions that led to the queue entry, even though file processing itself is stateless between runs
- Users can act on items individually or in bulk

### 15. Internationalisation (i18n)

- The tool's Web UI and user-facing messages are translatable to multiple languages
- Language selectable by the user in the UI
- Default language: English
- Translation system supports community contributions

---

## Deferred Features (designed for, not implemented)

- **OCR for image-based subtitles**: architecture supports a future custom OCR plugin for PGS/VOBSUB → SRT conversion
- **Subtitle downloading**: plugin hook for fetching missing subs from external sources (OpenSubtitles, Subscene, etc.)
- **Notifications**: webhook-based notifications for job failures and review queue items

---

## Non-Functional Requirements

- Single Docker container — no external services (no Redis, no separate worker container)
- Linux only
- PUID/PGID configurable via environment variables for correct file ownership on host-mounted volumes
- Worker concurrency configurable via `WORKER_CONCURRENCY` env var, default 1
- Both `docker run` and `docker-compose.yml` deployment options provided
- Log retention: configurable max log age or size, with automatic rotation
