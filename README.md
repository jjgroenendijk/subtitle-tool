# Subtitle Tool

Self-hosted tool that keeps the subtitle side of a Plex media library clean:
external UTF-8 SRT files, correct language codes in filenames Plex understands,
junk lines removed, and embedded subtitles extracted where wanted.

See [docs/architecture.md](docs/architecture.md) for the design and
[docs/plan.md](docs/plan.md) for the implementation milestones.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```sh
uv sync --extra dev      # create the environment
uv run pytest            # run the tests
uv run ruff check        # lint
uv run ruff format       # format
```

## Configuration

Bootstrap settings come from environment variables only: `CONFIG_DIR`, `PORT`,
`PUID`, `PGID`, and `TZ`. Everything else lives in a TOML config file in the
config directory (default `/config/config.toml`) and is validated on load; see
`src/subtitle_tool/config/`.
