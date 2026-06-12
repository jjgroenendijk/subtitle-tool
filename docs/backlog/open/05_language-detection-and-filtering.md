# Language Detection and Filtering

Milestone 5 in `docs/plan.md`.

## Goal

Confidence-scored language detection driving filename language codes and optional language filtering.

## Tasks

- Detection step using lingua: sample from the middle of the file with fallback for short files; output language plus confidence.
- Below the configured confidence threshold: no language-dependent action, warning recorded.
- Filename language handling: add or correct the ISO 639-1 code segment; on filename/detection disagreement rename only at high confidence, otherwise warn.
- Optional language filter: configured wanted-language set; unwanted subtitles deleted or kept-with-warning per configuration; default off.
- Undetectable-language handling per configuration (keep and warn by default).

## Done When

- Unit tests with fixture files in several languages, a short file, a mixed-language file, and a wrong-code-in-filename case.
