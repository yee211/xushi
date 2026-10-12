#!/bin/sh
set -eu
# Existing bind mounts may be owned by root. Bootstrap permissions, then drop privileges.
if [ "$(id -u)" = 0 ]; then
    mkdir -p /app/data /app/static/downloads
    chown -R xushi:xushi /app/data /app/static
    exec gosu xushi "$@"
fi
exec "$@"
