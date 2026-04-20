# Subtitle Tool — Functional Requirements

## Context

Homelab subtitle cleanup tool running as a Docker container alongside a media server (Plex). The goal is to enforce a clean, standardised subtitle state across a media library: external subs only, correct language tags, proper format, synced timing, and clean content.

---

## Functional Requirements

### 1. Subtitle Extraction

- Extract embedded text-based subtitle streams (SRT, ASS, SSA) from video files to external files
- Extract embedded image-based subtitle streams (PGS, VOBSUB) to external files
- **Configurable per format**: user selects which embedded subtitle formats to extract (e.g. extract SRT/ASS but leave PGS embedded)
- Remux the video file after extraction to remove extracted subtitle streams
- Remux output format is configurable: keep original extension (default), MKV, or MP4
- AVI files are not remuxed (AVI has no subtitle stream support)
- **Delete source toggle (video)**: after extraction + remux, delete original video file. Default: OFF (keep both)

### 2. Format Handling

- Convert ASS, SSA, and optionally VTT subtitle files to SRT
- Formats not in a configurable allowed-formats list are converted if possible, otherwise flagged
- Default allowed format: SRT
- PGS and VOBSUB: keep or delete based on language metadata. No OCR conversion (architecture designed for future custom OCR plugin)
- **Delete source toggle (subtitle)**: after conversion, delete original subtitle file. Default: OFF (keep both)

### 3. Language Detection

- Detect the language of each text-based subtitle file
- Sample subtitle blocks from the middle of the file, skipping a configurable number from the start and end (to avoid credits/recaps)
- Assign a confidence score to each detection
- Files below a configurable minimum confidence threshold are flagged for review (not acted on)
- **Multi-language subs**: detect dominant language, tag with that
- When a language code already exists in the filename but disagrees with detection: behaviour is configurable (rename, keep original, or flag for review)

### 4. Language Filtering

- User configures either a **whitelist** (only these languages kept) or a **blacklist** (these languages removed), not both
  - Whitelist mode: only subtitle files matching listed languages are kept
  - Blacklist mode: subtitle files matching listed languages are acted on, all others kept
  - Empty list = no filtering (all languages kept)
- **Action for filtered languages** is configurable:
  - Delete the subtitle file
  - Move to a configurable quarantine/output directory
  - Flag in review queue (no action taken)
- Configurable behaviour for subs whose language could not be detected: keep, delete, or flag for review
- Image-based subs with no metadata language tag: keep, delete, or flag for review (configurable)

### 5. Filename Normalisation

- Rename subtitle files to include the ISO 639-1 two-letter language code as the second-to-last dot-segment
  - Example: `Movie.2020.srt` → `Movie.2020.en.srt`
- **Flag normalisation**: standardise HI/SDH/forced flags to canonical forms
  - Configurable mapping (e.g. `.hi` / `.cc` → `.sdh`)
  - Auto-detect flags from subtitle content (e.g. `[HH]` markers → tag as SDH)
- Existing non-flag segments preserved

### 6. Encoding Normalisation

- Detect character encoding of all text-based subtitle files
- Convert all non-UTF-8 files to UTF-8

### 7. Content Cleanup

- **Ad/watermark removal**: remove known patterns ("Subtitles by...", "OpenSubtitles.org", site URLs, etc.)
- **Empty/broken block removal**: strip empty blocks, whitespace-only blocks, duplicate consecutive blocks
- **HI annotation removal** (optional, configurable): strip `[music]`, `(door slams)` etc. from non-SDH subtitle files
- **OCR error correction**: fix common OCR artifacts (l→I, 0→O patterns)
- **Artifact cleanup**: remove lone music note characters, leading/trailing punctuation artifacts
- All cleanup rules are configurable (enable/disable per rule type)

### 8. SRT Styling Cleanup

- Configurable per tag type: user can choose to keep or strip each of:
  - Italic tags (`<i>`)
  - Bold tags (`<b>`)
  - Color codes
  - Positioning/alignment tags
- Default: strip all (produce plaintext SRT)

### 9. Sync Correction

- **Audio-based sync**: sync subtitle against the video's audio track (primary method)
- **Reference-based sync**: sync against another subtitle file for the same video (fallback)
- Detect whether a subtitle is out of sync before attempting correction
- Skip sync if measured median offset is below configurable threshold (default: 500ms)
- Post-sync confidence measured by comparing median timing shift
- Revert sync output if median shift exceeds configurable limit (default: 30s)
- Low-confidence sync results flagged for review
- Only text-based formats are synced; image-based never synced

### 10. Deduplication

- After extraction, compare external subs with newly extracted ones
- Detect exact and near-exact duplicate subtitle files
- **Flag duplicates in UI** for user decision — do not auto-delete

### 11. Trigger Mechanisms

- **Scheduled scan**: configurable cron expression (default: 2:00 AM daily)
- **Filesystem watchdog**: inotify-based, process new/changed files automatically. 30-second debounce (configurable)
- **Manual trigger from UI**: full library scan or single file reprocess
- All triggers run in **config-trusted auto mode** — no confirmation step. Results logged.

### 12. File Discovery

- User configures one or more root media paths
- **Recursive scan mode** (default): scan all video + subtitle files recursively. Works with any folder structure.
- **Plex-aware mode** (optional): use Plex naming conventions (`Movie (Year)/Movie (Year).mkv`) to infer metadata and group related files
- Both modes can be active simultaneously on different paths

### 13. Web UI

- **Dashboard**: active job progress, stats, recent job history
- **Library browser**: searchable/filterable list of all media files with subtitle status
- **Review queue**: items flagged for manual decision (low-confidence detection, duplicates, ambiguous sync)
- **Configuration page**: all settings editable from UI, grouped by pipeline step
- **Job detail view**: live log streaming, per-step status
- **Cron field**: shows human-readable translation of cron expression in real-time

### 14. Configuration

- Two "delete source" toggles:
  - Delete original video after extraction + remux (default: OFF)
  - Delete original subtitle after conversion (default: OFF)
- Output location when not deleting source: configurable (same directory with different name, OR custom output directory)
- All pipeline steps individually configurable
- Config changes take effect on next run (no restart required)

### 15. Review Queue

- Items enter the queue only when the tool cannot make a confident decision:
  - Low-confidence language detection
  - Ambiguous sync results
  - Detected duplicates
  - Multi-language subs (informational flag)
  - Formats that can't be converted
- Users can act on items individually or in bulk

---

## Deferred Features (designed for, not implemented)

- **OCR for image-based subtitles**: architecture supports a future custom OCR plugin for PGS/VOBSUB → SRT conversion
- **Subtitle downloading**: plugin hook for fetching missing subs from external sources (OpenSubtitles, Subscene, etc.)

---

## Non-Functional Requirements

- Single Docker container — no external services (no Redis, no separate worker container)
- Linux only
- PUID/PGID configurable via environment variables for correct file ownership on host-mounted volumes
- Worker concurrency configurable via `WORKER_CONCURRENCY` env var, default 1
- Both `docker run` and `docker-compose.yml` deployment options provided
