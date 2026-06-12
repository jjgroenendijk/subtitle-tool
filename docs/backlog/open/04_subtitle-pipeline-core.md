# Subtitle Pipeline Core

Milestone 4 in `docs/plan.md`.

## Goal

The core file transformations, runnable via a CLI entry point against a real library, with dry-run support.

## Tasks

- Pipeline runner: applies enabled steps to each subtitle in dependency order, records actions and warnings per file, continues past per-file failures.
- Step: encoding detection (charset-normalizer) and UTF-8 conversion.
- Step: ASS/SSA/VTT to SRT conversion (pysubs2), opt-in deletion of the original.
- Step: content cleanup — ad/watermark line removal from a built-in pattern list, empty/broken/duplicate-consecutive block removal, artifact removal; rules individually toggleable.
- Step: filename normalization to Plex conventions, including `.forced` and `.sdh` flag standardization.
- Safety layer used by all steps: write to temp file on the same filesystem, validate (parseable, non-empty), atomic replace; collision handling via numeric suffix.
- Dry-run flag: full decision logic, no writes, actions reported as planned.
- Minimal CLI (`subtitle-tool scan --dry-run`) for use before the UI exists.

## Done When

- Each step has unit tests with fixture subtitle files covering good, broken, and already-clean inputs.
- End-to-end test: fixture library scanned in dry-run (no changes) and real mode (expected end state asserted).
