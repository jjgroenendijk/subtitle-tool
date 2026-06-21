# Embedded subtitle stream variants (issue #143)

## Problem

Real libraries carry several embedded subtitle streams for one language (normal, SDH/hearing
impaired, forced). The extraction phase only kept index, codec, and language, so same-language
streams were indistinguishable and extracted through collision suffixes (`Movie.en.srt`,
`Movie.en (1).srt`, `Movie.en (2).srt`) with no Plex variant flags.

## Investigation

- `ffprobe -show_entries stream_disposition` exposes `forced`, `hearing_impaired`, and `captions`
  flags per subtitle stream.
- A test MKV with three English subtitle streams reported:
  - normal English: no variant disposition
  - English SDH: `disposition.hearing_impaired = 1`
  - English forced: `disposition.forced = 1`
- Stream `title`/`name` tags (`English SDH`, `English Forced`) are a conservative title fallback
  when dispositions are silent.

## Approach

- New `pipeline/stream_variants.py`: `SubtitleVariant` enum (normal/forced/sdh/unknown) and a
  deterministic `classify_variant(disposition, title)`. Dispositions beat title heuristics;
  conflicting dispositions or conflicting title labels classify as `unknown`. Title heuristics only
  recognise clear labels (`forced`, `sdh`, `hearing impaired`, `cc`, `caption`).
- `pipeline/ffmpeg.py`: query `stream_disposition` and the `title` tag; `SubtitleStream` carries a
  `variant`.
- `config/models.py`: per-variant `StreamAction` (`extract` / `keep_embedded`) for normal, forced,
  sdh, and unknown streams. Defaults keep today's broad extraction for normal/forced/sdh and keep
  unknown streams embedded (never a destructive guess).
- `pipeline/video.py`: extracted names include `.forced` / `.sdh` flags before collision handling,
  dry-run mirrors real naming, remux drops only the streams selected for extraction.

## Status

Implemented with unit tests covering classification, ffprobe parsing, naming, dry-run naming, remux
drop selection, config validation, and web form persistence.
