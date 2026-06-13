# Subtitle Tool runtime image: the app plus a bundled ffmpeg/ffprobe.
#
# Dependencies are installed in their own layer (cached on lockfile changes) and
# the project on top, so source edits do not re-resolve the environment. The
# container starts as root only long enough for the entrypoint to align the
# runtime user with PUID/PGID, then drops privileges via gosu.

FROM python:3.14-slim

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
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the project itself.
COPY src ./src
RUN uv sync --frozen --no-dev

# Runtime user; the entrypoint re-points it at the requested PUID/PGID on start.
RUN groupadd -g 1000 app \
    && useradd -u 1000 -g app -d /config -s /usr/sbin/nologin app

VOLUME ["/config"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/health' % os.environ.get('PORT', '8000')).status == 200 else 1)"

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["subtitle-tool"]
