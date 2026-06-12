# Subtitle Extraction and Remux

Milestone 8 in `docs/plan.md`.

## Goal

Embedded text subtitles become clean external files; optionally the video is remuxed to drop them.

## Tasks

- ffprobe inspection of subtitle streams (codec, language tags).
- Extract wanted text-based streams to external SRT files; extracted files feed into the normal subtitle pipeline in the same run.
- Skip when no relevant streams exist; leave image-based streams (PGS/VOBSUB) embedded.
- Optional remux removing extracted streams: free-disk-space check, source size/mtime stability check before and after, temp output plus atomic replace, never remux AVI.
- Opt-in deletion of the original video after successful remux; default off.

## Done When

- Tests use small generated fixture videos (ffmpeg-created in test setup) covering extraction, no-op, and remux paths.
- A failed remux leaves the original video untouched.
