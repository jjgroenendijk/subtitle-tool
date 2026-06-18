"""JSON shapes for jobs returned by the API.

The HTML templates render :class:`~subtitle_tool.jobs.models.Job` objects directly;
the JSON API and these helpers exist for programmatic clients and tests. Summaries
omit per-file rows; the detail shape includes them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from subtitle_tool.index.models import IndexedSubtitle, LibraryVideo
    from subtitle_tool.jobs.models import Job, JobFile


def job_summary(job: Job) -> dict[str, Any]:
    """A job without its per-file rows, for list and creation responses."""
    return {
        "id": job.id,
        "mode": job.mode,
        "status": job.status.value,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "total_files": job.total_files,
        "changed_files": job.changed_files,
        "warning_count": job.warning_count,
        "error_files": job.error_files,
    }


def job_detail(job: Job) -> dict[str, Any]:
    """A job including its per-file results."""
    return {**job_summary(job), "files": [_file(file) for file in job.files]}


def _file(file: JobFile) -> dict[str, Any]:
    return {
        "source": file.source,
        "target": file.target,
        "changed": file.changed,
        "actions": [list(action) for action in file.actions],
        "warnings": file.warnings,
        "error": file.error,
    }


def library_video(video: LibraryVideo) -> dict[str, Any]:
    """A library video with its subtitle coverage and missing wanted languages."""
    return {
        "path": video.video.path,
        "languages": video.languages,
        "missing_languages": video.missing_languages,
        "subtitles": [_subtitle(sub) for sub in video.subtitles],
    }


def _subtitle(subtitle: IndexedSubtitle) -> dict[str, Any]:
    return {
        "path": subtitle.path,
        "language": subtitle.language,
        "flags": subtitle.flags,
        "matched": subtitle.matched,
    }
