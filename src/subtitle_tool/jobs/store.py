"""SQLite-backed job history.

One small database under ``/config`` holds every job, its per-file results, and
its warnings. There is no per-file media state here (the filesystem is the source
of truth for that); this is purely the record of what past runs did, for the UI to
display. The store is the single writer from the worker thread and a reader from
the web request handlers, so one connection guarded by a lock is enough; SQLite
serializes the rest.

Only files the run actually touched or had something to say about are stored
(actions, warnings, or an error); clean, unchanged files are omitted so history
stays compact on a large library. The summary counts are written onto the job row
at finish time so list views need no per-file scan.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from subtitle_tool.jobs.models import Job, JobFile, JobStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT,
    total_files INTEGER NOT NULL DEFAULT 0,
    changed_files INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_files INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    actions TEXT NOT NULL,
    warnings TEXT NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS job_files_job_id ON job_files(job_id);
"""


class JobStore:
    """A SQLite store for job history, safe to share across threads."""

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        path = Path(path)
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_job(self, mode: str) -> int:
        """Insert a running job and return its id."""
        started = datetime.now().astimezone().isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO jobs (mode, status, started_at) VALUES (?, ?, ?)",
                (mode, JobStatus.RUNNING.value, started),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def add_file(self, job_id: int, file: JobFile) -> None:
        """Record one file's outcome for a job."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_files (job_id, source, target, actions, warnings, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    file.source,
                    file.target,
                    json.dumps([list(action) for action in file.actions]),
                    json.dumps(file.warnings),
                    file.error,
                ),
            )
            self._conn.commit()

    def finish_job(
        self,
        job_id: int,
        status: JobStatus,
        *,
        total_files: int,
        changed_files: int,
        warning_count: int,
        error_files: int,
        error: str | None = None,
    ) -> None:
        """Mark a job finished and store its summary counts."""
        finished = datetime.now().astimezone().isoformat()
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, error = ?, total_files = ?, "
                "changed_files = ?, warning_count = ?, error_files = ? WHERE id = ?",
                (
                    status.value,
                    finished,
                    error,
                    total_files,
                    changed_files,
                    warning_count,
                    error_files,
                    job_id,
                ),
            )
            self._conn.commit()

    def mark_running_interrupted(self) -> int:
        """Mark any job still ``running`` as interrupted; return how many.

        Only one job runs at a time, so on startup a job left in ``running`` state
        belongs to a previous process that stopped mid-run. It is marked interrupted
        rather than resumed: the steps are idempotent and the next scan finishes the
        work.
        """
        finished = datetime.now().astimezone().isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ? WHERE status = ?",
                (JobStatus.INTERRUPTED.value, finished, JobStatus.RUNNING.value),
            )
            self._conn.commit()
            return cursor.rowcount

    def list_jobs(self, limit: int = 50) -> list[Job]:
        """Return recent jobs newest first, without their per-file rows."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def get_job(self, job_id: int) -> Job | None:
        """Return one job with its per-file results, or ``None`` if unknown."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            file_rows = self._conn.execute(
                "SELECT * FROM job_files WHERE job_id = ? ORDER BY id", (job_id,)
            ).fetchall()
        files = [_file_from_row(file_row) for file_row in file_rows]
        return _job_from_row(row, files)

    def prune(self, retention_limit: int) -> int:
        """Delete the oldest jobs beyond ``retention_limit``; return how many removed."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM jobs WHERE id NOT IN (SELECT id FROM jobs ORDER BY id DESC LIMIT ?)",
                (retention_limit,),
            )
            self._conn.commit()
            return cursor.rowcount


def _job_from_row(row: sqlite3.Row, files: list[JobFile] | None = None) -> Job:
    return Job(
        id=row["id"],
        mode=row["mode"],
        status=JobStatus(row["status"]),
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        error=row["error"],
        total_files=row["total_files"],
        changed_files=row["changed_files"],
        warning_count=row["warning_count"],
        error_files=row["error_files"],
        files=files or [],
    )


def _file_from_row(row: sqlite3.Row) -> JobFile:
    return JobFile(
        source=row["source"],
        target=row["target"],
        actions=[tuple(action) for action in json.loads(row["actions"])],
        warnings=json.loads(row["warnings"]),
        error=row["error"],
    )
