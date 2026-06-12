# Subtitle Tool — Functional Requirements

## Context

The tool keeps subtitles in a Plex media library clean and consistently organized. The user configures it once through a web interface; after that it runs unattended on a schedule. This document lists what the tool does for the user. How it is built is covered in `architecture.md`.

## Core Behavior

- Scan one or more configured media directories recursively.
- Pair external subtitle files with their video using filename matching; skip ambiguous pairs with a warning instead of guessing.
- Process files unattended on a configurable schedule, and on demand from the UI.
- Support a dry-run mode that reports what would change without touching files.
- Never perform a destructive action the tool is not confident about; skip and explain instead.

## Subtitle Extraction

- Extract embedded text-based subtitle streams from video files to external SRT files, filtered by the configured languages.
- Optionally remux the video afterwards to remove extracted streams. Default: off.
- Optionally delete the original video after a successful remux. Default: off.
- Image-based streams (PGS, VOBSUB) are left embedded; OCR is out of scope.

## Encoding and Format

- Detect the character encoding of text subtitles and convert to UTF-8.
- Convert ASS, SSA, and VTT subtitles to SRT.
- Optionally delete the original after successful conversion. Default: off.

## Language Handling

- Detect the language of each text subtitle with a confidence score.
- Skip language-dependent actions when confidence is below a configurable threshold, with a warning.
- Optionally filter subtitles to a configured set of wanted languages; unwanted ones are deleted or kept with a warning, per configuration. Default: no filtering.
- When the language code in a filename disagrees with detection, rename only when detection confidence is high; otherwise warn.

## Content Cleanup

- Remove known subtitle ads and watermark lines.
- Remove empty, broken, and duplicate consecutive blocks.
- Remove simple artifacts such as lone music notes and punctuation leftovers.
- Optionally strip styling tags (italics, color, positioning). Default: keep.
- Cleanup rules can be toggled individually.

## Filename Normalization

- Rename subtitle files to the Plex convention: video basename plus an ISO 639-1 language code, for example `Movie (2020).en.srt`.
- Standardize forced and SDH/HI flags as `.forced` and `.sdh` segments.
- When the language cannot be determined confidently, leave the filename unchanged and warn.

## Sync Correction (later milestone)

- Correct subtitle timing against the video's audio track.
- Apply a correction only when the measured offset exceeds a minimum threshold and the result confidence is high; otherwise skip with a warning.
- Cap the maximum automatic shift; larger corrections become warnings.

## Web UI

- Configuration page covering all settings, persisted across restarts.
- Dashboard with current job progress and recent job history.
- Job detail view with per-file results, actions taken, and warnings with skip reasons.
- Buttons to trigger a scan now, in dry-run or real mode.

## Configuration

- All settings are edited in the web UI and stored in a single config file in the `/config` volume; changes apply on the next run without a restart.
- Environment variables are used only for bootstrap settings: port, config directory, PUID/PGID, timezone.
- Exclude patterns let the user keep paths or filename patterns out of scans.

## Deferred

OCR conversion of image-based subtitles, subtitle downloading from external providers, filesystem watching, notifications, authentication, and UI translations.
