# Subtitle Tool runtime image: the app plus a bundled ffmpeg/ffprobe.
#
# Dependencies are installed in their own layer (cached on lockfile changes) and
# the project on top, so source edits do not re-resolve the environment. The
# container starts as root only long enough for the entrypoint to align the
# runtime user with PUID/PGID, then drops privileges via gosu.

# Pinned to a digest so each base image rebuild is an explicit, reviewable
# dependency change rather than a silent floating-tag update. Keep the
# human-readable tag alongside the digest; Dependabot's docker ecosystem updates
# both together (see .github/dependabot.yml).
FROM python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061

# uv provides fast, lockfile-pinned dependency installation.
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# ffmpeg/ffprobe are required by the extraction and remux pipeline; gosu drops
# privileges to the runtime user; passwd supplies usermod/groupmod.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gosu passwd \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000 \
    CONFIG_DIR=/config

WORKDIR /app

# Install dependencies first so source changes do not invalidate this layer.
# ffsubsync pulls webrtcvad-wheels, a C extension with no wheel for every Python
# version; build it with a temporary toolchain that is purged in the same layer so
# the runtime image stays slim.
COPY pyproject.toml uv.lock README.md ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && uv sync --frozen --no-dev --no-install-project \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install the project itself.
COPY src ./src
RUN uv sync --frozen --no-dev

# Runtime user; the entrypoint re-points it at the requested PUID/PGID on start.
RUN groupadd -g 1000 app \
    && useradd -u 1000 -g app -d /config -s /usr/sbin/nologin app

VOLUME ["/config"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/health/ready' % os.environ.get('PORT', '8000')).status == 200 else 1)"

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["subtitle-tool"]
