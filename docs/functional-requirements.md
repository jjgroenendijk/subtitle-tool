# Subtitle Tool — Functional Requirements

## Context

The Subtitle Tool runs alongside a media server and helps keep a media library in a clean subtitle state: external subtitles, correct language tags, preferred formats, clean content, and corrected timing where possible.

## Functional Requirements

### 1. Subtitle Extraction

- Extract embedded text-based subtitle streams from video files to external subtitle files.
- Extract embedded image-based subtitle streams from video files to external subtitle files.
- Let the user choose which embedded subtitle formats should be extracted.
- Remux the video file after extraction so extracted subtitle streams are removed from the video.
- Let the user choose the remux target container format: keep original extension, MKV, or MP4.
- Let the user choose whether the original video is deleted after successful extraction and remux. Default: OFF.
- If the original video is retained, let the user choose where the processed output is written:
  - Same directory with a configured prefix or suffix.
  - Custom output directory.

### 2. Encoding Normalisation

- Detect the character encoding of text-based subtitle files.
- Convert subtitle files to UTF-8 when needed.

### 3. Format Handling

- Convert ASS, SSA, and optionally VTT subtitle files to SRT.
- Let the user define which subtitle formats are allowed.
- Keep or remove PGS and VOBSUB subtitles based on configured language-handling rules.
- Do not perform OCR conversion for image-based subtitles in v1.
- Let the user choose whether the original subtitle file is deleted after successful conversion. Default: OFF.

### 4. Language Detection

- Detect the language of each text-based subtitle file.
- Assign a confidence score to each language detection result.
- Let the user configure the minimum confidence threshold.
- For subtitles containing multiple languages, assign a single language tag based on the dominant detected language.
- When a language code already exists in the filename but disagrees with detection, let the user choose whether to rename it, keep it, or skip renaming with a warning.

### 5. Language Filtering

- Let the user configure either a whitelist or a blacklist of subtitle languages.
- Treat an empty language list as no filtering.
- Let the user choose what happens to filtered subtitles:
  - Delete them.
  - Move them to quarantine.
  - Keep them and emit a warning.
- Let the user choose what happens when subtitle language cannot be detected.
- Let the user choose what happens to image-based subtitles that have no usable language metadata.

### 6. Content Cleanup

- Remove known subtitle ads and watermark text.
- Remove empty, broken, or duplicate consecutive subtitle blocks.
- Optionally remove hearing-impaired annotations from non-SDH subtitles.
- Remove simple subtitle artifacts such as lone music notes and punctuation leftovers.
- Let the user choose whether to keep or strip common SRT styling elements such as italics, bold, color, and positioning tags.
- Let the user enable or disable cleanup rules individually.

### 7. Filename Normalisation

- Rename subtitle files to include a standardized language code as the second-to-last filename segment.
- Prefer ISO 639-1 language codes when available, with fallback to ISO 639-2/3 where needed.
- Standardize HI, SDH, and forced-subtitle filename flags.
- Preserve existing non-flag filename segments.
- When language cannot be determined confidently, preserve the existing language segment or leave it absent by default.
- Let the user optionally force filename language renaming even for low-confidence detections.

### 8. Deduplication

- Detect duplicate subtitle files associated with the same media item.
- Do not delete detected duplicates automatically.
- Warn the user when duplicates are detected and explain why automatic action was skipped.

### 9. Sync Correction

- Support subtitle sync correction against the associated video's audio track.
- Detect whether a subtitle is out of sync before attempting correction.
- Let the user configure the minimum offset threshold required before a sync correction is applied.
- Let the user configure a maximum allowed timing shift for automatic correction.
- Skip ambiguous or low-confidence sync results and show a warning with the reason.
- Only sync text-based subtitles in v1.

### 10. Trigger Mechanisms

- Support scheduled scans using a cron expression.
- Support automatic processing of new or changed files through filesystem watching.
- Support manual scans from the UI for the full library or a single file.
- For scheduled and watchdog-triggered runs, let the user choose between immediate execution and waiting for confirmation in the UI.
- Manual runs must show planned actions before execution.

### 11. File Discovery

- Let the user configure one or more root media paths.
- Support recursive scanning by default.
- Associate subtitle files with the correct video file using deterministic matching rules.
- Skip ambiguous subtitle-to-video matches instead of guessing, and show a warning with the reason.
- Let the user exclude configured paths and patterns from scanning.

### 12. Web UI

- Show a dashboard with active job progress, statistics, and recent job history.
- Show scan results with per-file current state and planned actions.
- Provide a searchable and filterable library browser.
- Show warnings and skipped-file explanations in scan results and job details.
- Provide a configuration page for all supported settings.
- Provide a job detail view with live progress, per-action status, and error details.
- Show a human-readable interpretation of cron expressions while editing schedules.

### 13. Configuration

- Provide separate delete-source options for videos and subtitle files.
- Let the user choose the output location when the source file is retained.
- Support a user-editable ignore file for excluding paths or filename patterns from future scans.
- Let the user configure whether successfully processed items are automatically added to the ignore file. Default: enabled.
- Support two source-retention modes:
  - Convergent mode.
  - Archive/export mode.
- Let the user configure a quarantine directory that is separate from the normal output directory.
- Let the user enable or disable pipeline steps individually.
- Make all settings configurable through the Web UI and environment variables.
- Apply configuration changes on the next run without requiring a restart.

### 14. Warnings and Skipped Files

- When the tool cannot make a confident automatic decision, it must skip the unsafe action and record a warning.
- Warnings must explain why the action was skipped and what condition prevented automatic processing.
- Warnings must be visible in scan results and job details.
- Skipped items are not managed through a persistent queue in v1.

### 15. Internationalisation

- Make the Web UI and user-facing messages translatable into multiple languages.
- Let the user choose the active UI language.
- Default the UI language to English.

## Deferred Features

- OCR conversion for image-based subtitles through a future plugin or extension point.
- Subtitle downloading from external providers through a future plugin or extension point.
- Webhook notifications for job failures and skipped-file warnings.
