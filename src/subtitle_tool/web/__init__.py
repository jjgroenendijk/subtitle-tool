"""Web application: the FastAPI app serving the UI and JSON API.

For now this is a stub exposing only the health endpoint so the container has a
liveness check from the start; the UI and the rest of the API arrive in later
milestones.
"""

from subtitle_tool.web.app import create_app

__all__ = ["create_app"]
