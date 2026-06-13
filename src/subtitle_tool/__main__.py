"""Console entry point: dispatch to the CLI.

Invoked as ``subtitle-tool`` (console script) or ``python -m subtitle_tool``. With
no arguments it serves the web app; the ``scan`` subcommand runs the pipeline once.
The argument parsing and command dispatch live in :mod:`subtitle_tool.cli`.
"""

from __future__ import annotations

import sys

from subtitle_tool.cli import main


def _main() -> None:
    raise SystemExit(main(sys.argv[1:]))


if __name__ == "__main__":
    _main()
