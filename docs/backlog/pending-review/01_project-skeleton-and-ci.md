# Project Skeleton and CI

Milestone 1 in `docs/plan.md`.

## Goal

A Python project where lint and tests run locally and in CI from the first commit.

## Tasks

- Create the package layout: `src/subtitle_tool/`, `tests/`, `pyproject.toml` with uv-compatible metadata.
- Implement configuration model: dataclass/pydantic settings loaded from a TOML or YAML file in the config directory, with validation and defaults matching `docs/technical-requirements.md`.
- Add bootstrap environment variables: `CONFIG_DIR`, `PORT`, `PUID`, `PGID`, `TZ`.
- Set up pytest with a first test for config loading and validation.
- Set up ruff (lint plus format).
- GitHub Actions workflow: ruff and pytest on every push and pull request.

## Done When

- `uv run pytest` and `uv run ruff check` pass locally and in CI.
- Invalid config files are rejected with a clear error message.
