# Container Build and GHCR Publishing

Milestone 2 in `docs/plan.md`.

## Goal

A container image that runs the app with ffmpeg bundled, published automatically to GitHub Container Registry.

## Tasks

- Dockerfile: Python 3.12 base, install ffmpeg, install the package, run as configurable PUID/PGID user, expose the web port, declare the `/config` volume.
- Entrypoint script handling PUID/PGID ownership setup.
- `docker-compose.yml` example with `/config` and a media mount.
- GitHub Actions workflow: build the image on every push; push to `ghcr.io/jjgroenendijk/subtitle-tool` with `latest` on main and version tags on releases.
- Health endpoint stub so container liveness checks work from the start.

## Done When

- `docker compose up` starts the container and the health endpoint responds.
- A tagged release publishes a pullable image on GHCR.
