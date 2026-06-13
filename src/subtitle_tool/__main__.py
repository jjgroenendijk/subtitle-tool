"""Console entry point: serve the web app with uvicorn.

Reads bootstrap settings from the environment (``PORT`` in particular) and binds
to all interfaces so the container's published port is reachable. Invoked as
``subtitle-tool`` (console script) or ``python -m subtitle_tool``.
"""

from __future__ import annotations

import uvicorn

from subtitle_tool.config import load_bootstrap
from subtitle_tool.web import create_app


def main() -> None:
    """Start the web server, listening on the bootstrap port."""
    bootstrap = load_bootstrap()
    uvicorn.run(create_app(), host="0.0.0.0", port=bootstrap.port)


if __name__ == "__main__":
    main()
