"""Command-line interface, used to run scans before the web UI exists.

``subtitle-tool`` with no arguments (or ``serve``) starts the web server, the
default a container runs. ``subtitle-tool scan`` runs one scan-and-process pass over
the library and prints a per-file report; ``--dry-run`` reports what it would do
without writing anything. Media paths may be given on the command line for a quick
ad-hoc run; otherwise they come from the persisted config file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from subtitle_tool.config import load_bootstrap, load_config
from subtitle_tool.config.loader import ConfigError
from subtitle_tool.config.models import Config
from subtitle_tool.pipeline import PipelineResult, run_pipeline
from subtitle_tool.scanner import scan


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``subtitle-tool`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return _run_scan(args)
    return _serve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subtitle-tool", description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="run the web server (default)")
    scan_parser = subparsers.add_parser("scan", help="scan and process the library once")
    scan_parser.add_argument(
        "paths",
        nargs="*",
        help="media paths to scan; overrides the config file's media paths when given",
    )
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report planned actions without modifying any files",
    )
    scan_parser.add_argument(
        "--config",
        type=Path,
        help="path to the config file (default: CONFIG_DIR/config.toml)",
    )
    return parser


def _serve() -> int:
    # Imported lazily so a scan does not pull in the web server and uvicorn.
    import uvicorn

    from subtitle_tool.web import create_app

    bootstrap = load_bootstrap()
    uvicorn.run(create_app(), host="0.0.0.0", port=bootstrap.port)
    return 0


def _run_scan(args: argparse.Namespace) -> int:
    try:
        config = _resolve_config(args)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 2

    if not config.scan.media_paths:
        print("[ERROR] no media paths configured; pass paths on the command line or set them")
        return 2

    scan_result = scan(config)
    result = run_pipeline(scan_result, config, dry_run=args.dry_run)
    _print_report(result)
    return 0


def _resolve_config(args: argparse.Namespace) -> Config:
    if args.paths:
        # An ad-hoc run: use defaults but point at the requested paths.
        return Config.model_validate({"scan": {"media_paths": args.paths}})
    config_path = args.config or load_bootstrap().config_file
    return load_config(config_path)


def _print_report(result: PipelineResult) -> None:
    mode = "dry-run" if result.dry_run else "real"
    verb = "would change" if result.dry_run else "changed"
    changed = result.changed_files
    print(f"[INFO] scan complete ({mode}): {len(changed)} file(s) {verb}")

    for file_result in changed:
        print(f"\n{file_result.source}")
        if file_result.target != file_result.source:
            print(f"  -> {file_result.target}")
        for action in file_result.actions:
            print(f"  [{action.type.value}] {action.description}")

    warnings = result.warnings
    if warnings:
        print(f"\n[WARNING] {len(warnings)} warning(s):")
        for message in warnings:
            print(f"  - {message}")

    errors = result.errors
    if errors:
        print(f"\n[ERROR] {len(errors)} file(s) failed:")
        for file_result in errors:
            print(f"  - {file_result.source}: {file_result.error}")
