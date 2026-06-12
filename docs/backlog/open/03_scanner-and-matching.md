# Scanner and Subtitle-to-Video Matching

Milestone 3 in `docs/plan.md`.

## Goal

Given configured media paths, produce a correct inventory of videos, their matched subtitles, and standalone subtitles.

## Tasks

- Recursive directory walker honoring configured exclude patterns (gitignore-style).
- Classify files by extension into videos and subtitles.
- Matcher applying rules in order: exact basename, normalized basename similarity, season/episode or movie/year parsing.
- Ambiguous matches produce a standalone subtitle plus a structured warning with the reason; never guess.
- Result model: list of video groups (video plus subtitles) and standalone subtitles, each carrying warnings.

## Done When

- Unit tests cover exact match, suffix variants (`.en`, `.en.sdh`, `.forced`), episode parsing, ambiguous cases, and exclude patterns, using temporary directory trees.
