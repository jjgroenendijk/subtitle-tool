# Subtitle Tool — Implementation Plan

Milestones build on each other; each one ends in a working, tested, shippable state. Detailed tasks live in `docs/backlog/open/`.

## Milestone 1: Skeleton and CI

Python package layout, configuration loading and validation, pytest with a first real test, ruff, and a GitHub Actions workflow running lint and tests on every push. Outcome: a repo where every later change is tested by default.

## Milestone 2: Container and GHCR Publishing

Dockerfile bundling ffmpeg, a compose example with PUID/PGID, and a workflow that builds on every push and publishes to GitHub Container Registry on tags and main. Outcome: `docker compose up` works from day one, even while the app does little.

## Milestone 3: Scanner and Matching

Directory walking with exclude patterns, video/subtitle discovery, and subtitle-to-video matching with skip-and-warn for ambiguous cases. Outcome: a dry scan that correctly inventories a library.

## Milestone 4: Subtitle Pipeline Core

The file-level transformations: UTF-8 normalization, ASS/SSA/VTT to SRT conversion, content cleanup rules, and Plex filename normalization, all behind the temp-file-plus-atomic-replace safety rule and a dry-run flag. Outcome: the tool produces real value on a library via CLI invocation, before any UI exists.

## Milestone 5: Language Detection and Filtering

Confidence-scored language detection, language-code renaming, and optional language filtering, gated by the confidence threshold. Outcome: filenames carry correct language codes; unwanted languages handled per configuration.

## Milestone 6: Web UI and Job History

FastAPI app: configuration page writing the config file, scan-now buttons (dry-run and real), dashboard with job progress via polling, job detail view with per-file results and warnings, SQLite job history, health endpoint. Outcome: the tool is fully usable without touching a terminal.

## Milestone 7: Scheduler and Unattended Operation

Interval-based scheduling, optional scan on startup, single-worker job queue with trigger collapsing, job retention pruning. Outcome: configure once, runs unattended — the core promise of the tool.

## Milestone 8: Extraction and Remux

ffprobe stream inspection, extraction of wanted text streams to external SRT, optional remux with disk-space and file-stability checks, opt-in source deletion. Outcome: embedded subtitles become clean external files.

## Milestone 9: Sync Correction

ffsubsync integration with offset threshold, confidence acceptance, shift cap, and per-file timeout. Outcome: out-of-sync subtitles are fixed automatically when safe.

Milestones 1 through 7 make the tool genuinely useful; 8 and 9 are heavier and can land at hobby pace afterwards.
