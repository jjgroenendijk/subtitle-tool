# Subtitle Tool — Functional Requirements

## Context

The tool keeps subtitles in a Plex media library clean and consistently organized. The user
configures it once through a web interface; after that it runs unattended on a schedule. This
document lists what the tool does for the user. How it is built is covered in `architecture.md`.

## Core Behavior

- Scan one or more configured media directories recursively. Symlinks are treated as plain entries:
  symlinked directories are not descended into (mount each media volume directly instead of linking
  across them), while a symlinked file is processed like any other file.
- Pair external subtitle files with their video using filename matching; skip ambiguous pairs with a
  warning instead of guessing.
- Process files unattended on a configurable schedule, and on demand from the UI.
- Watch the media directories and automatically process new or changed videos and subtitles shortly
  after they appear, waiting until files have finished copying. Watching can be disabled in the
  configuration.
- Support a dry-run mode that reports what would change without touching files.
- Never perform a destructive action the tool is not confident about; skip and explain instead.

## Subtitle Extraction

- Extract embedded text-based subtitle streams from video files to external SRT files, filtered by
  the configured languages.
- Distinguish embedded stream variants from their ffprobe metadata: normal/full, forced,
  SDH/hearing-impaired/caption, and unknown (ambiguous or conflicting) streams. Dispositions are
  authoritative; the stream title is a conservative fallback only when no disposition is set.
- Choose per variant what happens to a stream: extract it to an external SRT (and drop it on remux),
  or keep it embedded. Defaults extract normal, forced, and SDH streams and keep unknown streams
  embedded so an ambiguous stream is never guessed into a destructive action.
- Choose how many eligible variants to keep per video/language: all of them, or only the single most
  preferred one. A preference order (default normal, then SDH, then forced) ranks the variants, so a
  policy of "normal first, SDH fallback, one final subtitle" extracts the normal stream when it
  exists and the SDH stream only when no normal stream exists, ending with one external subtitle per
  language instead of one per variant. Default: keep all eligible variants. Eligibility and language
  filtering apply first; selection only decides among the streams that pass both.
- Name extracted files with Plex-compatible variant flags: normal as `<video>.<lang>.srt`, forced as
  `<video>.<lang>.forced.srt`, and SDH/caption as `<video>.<lang>.sdh.srt`, so same-language
  variants stay distinct instead of collapsing into numeric collision suffixes.
- Optionally remux the video afterwards to remove the extracted streams; streams kept embedded are
  preserved. Default: off.
- Optionally delete the original video after a successful remux. Default: off.
- Image-based streams (PGS, VOBSUB) are left embedded; OCR is out of scope.

## Encoding and Format

- Detect the character encoding of text subtitles and convert to UTF-8.
- Convert ASS, SSA, and VTT subtitles to SRT.
- Optionally delete the original after successful conversion. Default: off.

## Language Handling

- Detect the language of each text subtitle with a confidence score.
- Skip language-dependent actions when confidence is below a configurable threshold, with a warning.
- Optionally filter subtitles to a configured set of wanted languages; unwanted ones are deleted or
  kept with a warning, per configuration. Default: no filtering.
- When the language code in a filename disagrees with detection, rename only when detection
  confidence is high; otherwise warn.
- Languages are chosen in the web UI from a predefined list of selectable languages, labelled with a
  readable name and code, instead of typed as raw codes. This covers both the extraction languages
  and the wanted-language filter; the stored value stays a list of Plex-compatible ISO 639-1 codes.

## Content Cleanup

- Remove known subtitle ads and watermark lines.
- Remove empty, broken, and duplicate consecutive blocks.
- Remove simple artifacts such as lone music notes and punctuation leftovers.
- Optionally strip styling tags (italics, color, positioning). Default: keep.
- Cleanup rules can be toggled individually.

## Filename Normalization

- Rename subtitle files to the Plex convention: video basename plus an ISO 639-1 language code, for
  example `Movie (2020).en.srt`.
- Standardize forced and SDH/HI flags as `.forced` and `.sdh` segments.
- When the language cannot be determined confidently, leave the filename unchanged and warn.

## Sync Correction

- Correct subtitle timing against the matched video's audio track, off by default.
- Apply a correction only when the measured offset exceeds a minimum threshold, the alignment score
  clears an acceptance threshold, and the absolute shift stays under a safety cap; otherwise keep
  the original timings and warn.
- Skip with a warning when the video has no usable audio track.
- Give each file a time budget; on timeout skip that file with a warning and continue the job.
- Only video-matched SRT subtitles are corrected; standalone subtitles are left untouched.

## Library Index and Reporting

- Maintain an index of the media library — videos and their matched subtitles — that the UI can
  browse without triggering a rescan.
- Report which videos are missing a wanted subtitle language, so gaps in coverage are visible at a
  glance.
- Retain a history of subtitle changes for audit, beyond the per-job history.
- The index is rebuilt automatically by a full scan, so it can be discarded to force full
  reprocessing.

## Web UI

- Configuration page covering all settings, persisted across restarts.
- Dashboard with current job progress and recent job history.
- Job detail view with per-file results, actions taken, and warnings with skip reasons. It also
  shows scan-coverage counters so a number such as files changed is never misread as the library
  size: videos found and subtitles found (the inventory the scan saw), files processed against the
  work the run targeted, unwanted subtitles the language filter deletes, and the existing changed,
  warning, and files-with-errors counts. The dashboard recent-jobs table carries the same coverage
  at a glance. A dry run counts planned work — planned deletes as unwanted, planned changes as
  changed — but writes nothing, including the media index, so the inventory it reconciles against is
  left unchanged. One consequence of writing nothing: a dry run that would extract embedded
  subtitles records the planned extraction but never creates those files, so it does not process
  them and its processed and total counts can be lower than the equivalent real run's. The job
  detail page always shows a start/completion notice for the job's state (started and running,
  completed, cancelled, interrupted, or failed), so a scan that finishes before the page renders
  still gives honest confirmation that it ran rather than appearing to be a silent no-op.
- Library view listing indexed videos, their subtitle languages and flags, and missing wanted
  languages, presented as a data table whose useful columns (video name, subtitle count,
  missing-wanted count, size, modified) the user can sort ascending or descending. The library shows
  coverage as a compact summary line rather than dashboard-style stat cards, so the table is the
  focus.
- A configuration maintenance action to clear the rebuildable media index, so the next scan
  reprocesses the entire library. It is presented as a deliberate, separate control with a
  confirmation step and copy explaining that it forces a full rebuild; it never changes
  configuration or media files.
- Buttons to trigger a scan now, in dry-run or real mode.
- A control to stop the job that is currently running, on both the dashboard and the running job's
  detail page. Stopping is cooperative and safe: the job ends at the next file boundary without
  leaving a partially written file, finishes with a distinct `cancelled` status shown in live
  progress and history, and any queued follow-up run is dropped rather than started.
- Primary navigation is a left-side menu on desktop layouts that stays visible (sticky) while the
  page scrolls, so links remain reachable on long dashboard, job detail, and configuration pages. On
  narrow or mobile screens it collapses to a persistent top bar that stays usable. The current route
  is visibly highlighted and exposes its current-page state accessibly (`aria-current="page"`).
- Page content uses the full width available beside the navigation rail on desktop and stays
  readable on narrow and mobile layouts.
- The visual treatment is a translucent, layered interface: layered translucent surfaces, depth, and
  light/dark contrast (following the operating system setting), adapted to sharp edges and corners
  so the UI reads as crisp and utilitarian rather than soft or pill-shaped. See
  `design-requirements.md` for the full visual direction.

## Configuration

- All settings are edited in the web UI and stored in a single config file in the `/config` volume;
  changes apply on the next run without a restart.
- Environment variables are used only for bootstrap settings: port, config directory, PUID/PGID,
  timezone, directory-picker root.
- Exclude patterns let the user keep paths or filename patterns out of scans.
- Media directories are chosen through a directory selection flow that browses the container's own
  filesystem, so the saved paths are server/container-visible and usable by the scanner without
  typing full paths by hand. Manual entry remains available as an advanced fallback. A configured
  path that is not a directory visible inside the container is flagged with a warning.

## Deferred

OCR conversion of image-based subtitles, subtitle downloading from external providers,
notifications, authentication, and UI translations.
