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

## Outcome

Implemented on branch `feat/language-detection`.

- Added `lingua-language-detector` dependency.
- New pipeline step `pipeline/steps/detection.py` (`detect_language`): samples
  dialogue from the middle of the file (whole file when short), detects language plus
  confidence via lingua, and gates every language-dependent action on
  `language.min_confidence`.
- Detection feeds the naming step a decided code through `WorkItem.language`: fills a
  missing code, corrects a disagreeing one when `rename_to_detected` is on, otherwise
  warns. Naming prefers `WorkItem.language` over the filename token.
- Language filtering: unwanted detected languages are deleted (`WorkItem.delete_file`
  plus new `ActionType.DELETE_FILTERED`, handled in the runner's commit) or kept with
  a warning per `language.filter.action`; default off.
- Low-confidence and undetectable files are kept with a warning (no rename, no
  filtering), honouring the never-guess rule.
- Step wired into the runner between cleanup and naming.
- Tests: `tests/pipeline/test_detection.py` (several languages, short file,
  mixed-language file, wrong-code-in-filename, filter delete/warn/keep) plus
  end-to-end rename-correction, filter-delete, and dry-run-safety cases in
  `tests/pipeline/test_runner.py`.
- `Tests: uv run pytest` (110 passed), `uv run ruff check`, `uv run ruff format --check`.
