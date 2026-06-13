# Media Index

Milestone 10 in `docs/plan.md`.

## Goal

Maintain a SQLite media index of videos and subtitles that scans reconcile
against, so unchanged files are skipped, missing wanted languages are reported,
and the library can be browsed in the UI without re-walking the disk.

## Tasks

- Index store (`index.db`) under the config dir, mirroring the connection and
  setup pattern of `JobStore` (`src/subtitle_tool/jobs/store.py`): a
  `threading.Lock`-guarded `sqlite3` connection and `CREATE TABLE IF NOT EXISTS`
  schema created on init.
- Schema for videos and subtitles: path (identity), fingerprint (size, mtime),
  parsed language and flags, subtitle-to-video match status, and
  first-seen / last-seen / last-changed timestamps.
- Reconciliation during a scan: rows are derived from the scan inventory
  (`VideoGroup`, `StandaloneSubtitle`, `ScanResult` in
  `src/subtitle_tool/scanner/models.py`) and parsed metadata
  (`split_subtitle_name` in `src/subtitle_tool/scanner/matching.py`). A file
  whose fingerprint matches its row is skipped; new or changed files are
  processed; vanished files are marked gone.
- Missing-wanted-language reporting: per video, list configured wanted languages
  that have no matching subtitle.
- Subtitle change/audit history retained beyond per-job history.
- Web library view listing indexed videos, their subtitle languages and flags,
  and missing wanted languages.
- The index is rebuildable: deleting `index.db` and running a full scan
  repopulates it; pipeline steps stay idempotent so a stale index is never
  unsafe.

## Done When

- Unit tests cover index reconciliation: new file inserted, unchanged file
  skipped, changed file (size/mtime) reprocessed, removed file marked gone, and
  missing-wanted-language reporting, using temporary directory trees and a
  temporary `index.db`.
- The library view renders indexed videos with languages, flags, and gaps.
