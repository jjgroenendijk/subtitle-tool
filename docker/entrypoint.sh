#!/bin/sh
# Align the runtime user with the requested PUID/PGID, hand the config volume to
# it, then drop privileges and exec the app. Running as a configurable uid/gid
# keeps files the tool writes owned the same way as the Plex media library.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
CONFIG_DIR="${CONFIG_DIR:-/config}"

if [ "$(id -g app)" != "$PGID" ]; then
    groupmod -o -g "$PGID" app
fi
if [ "$(id -u app)" != "$PUID" ]; then
    usermod -o -u "$PUID" app
fi

# The config volume is mounted at runtime, so ownership has to be set here.
chown app:app "$CONFIG_DIR" 2>/dev/null || true

exec gosu app "$@"
