"""Web application: the FastAPI app serving the UI and JSON API.

:func:`create_app` builds the app and its background machinery (config, SQLite job
history, event broker, worker) and registers the dashboard, job detail, and
configuration pages, the Server-Sent Events stream, the JSON API, and the health
probe. See :mod:`subtitle_tool.web.app`.
"""

from subtitle_tool.web.app import create_app

__all__ = ["create_app"]
