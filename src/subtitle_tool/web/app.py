"""The FastAPI application factory.

The app is intentionally minimal at this milestone: it exposes a single health
endpoint used by container liveness checks. Later milestones add the
configuration UI, scan triggers, job history, and Server-Sent Events on top of
the same app instance.
"""

from __future__ import annotations

from fastapi import FastAPI

from subtitle_tool import __version__


def create_app() -> FastAPI:
    """Build the FastAPI application.

    Using a factory keeps construction explicit and testable: tests build their
    own instance, and the server entry point builds the one it serves.
    """
    app = FastAPI(title="Subtitle Tool", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness probe. Returns a static OK payload while the app is running."""
        return {"status": "ok", "version": __version__}

    return app
