"""Job history and the background worker that produces it.

The :class:`~subtitle_tool.jobs.store.JobStore` persists every run to SQLite, the
:class:`~subtitle_tool.jobs.broker.EventBroker` pushes live progress to connected
browsers over SSE, and the :class:`~subtitle_tool.jobs.worker.Worker` runs one scan
at a time on a background thread, feeding both.
"""

from subtitle_tool.jobs.broker import EventBroker
from subtitle_tool.jobs.models import Job, JobFile, JobStatus
from subtitle_tool.jobs.store import JobStore
from subtitle_tool.jobs.worker import Worker

__all__ = [
    "EventBroker",
    "Job",
    "JobFile",
    "JobStatus",
    "JobStore",
    "Worker",
]
