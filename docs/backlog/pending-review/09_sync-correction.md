# Sync Correction

Milestone 9 in `docs/plan.md`.

## Goal

Out-of-sync text subtitles are corrected against the video's audio when the result is trustworthy.

## Tasks

- ffsubsync integration for video-matched text subtitles.
- Apply a correction only when: measured offset exceeds the configured minimum, result confidence exceeds the acceptance threshold, and the absolute shift stays under the safety cap. Otherwise revert and warn.
- Per-file timeout; on timeout skip with a warning and continue the job.
- Skip with a warning when the video has no usable audio track.
- Configuration: enable flag (default off), thresholds, cap, timeout.

## Done When

- Tests with a fixture video and a deliberately shifted subtitle: correction applied within thresholds, skipped beyond the cap, reverted on low confidence.
