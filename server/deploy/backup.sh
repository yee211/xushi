#!/bin/sh
set -eu
umask 077
root=/backups
source_data=/source-data
mkdir -p "$root"

backup_once() (
    bundle="$root/xushi_bundle_$(date -u +%Y%m%dT%H%M%SZ)"
    pending="$bundle.pending"
    mkdir "$pending" || exit 1
    trap 'find "$pending" -type f -delete; rmdir "$pending" 2>/dev/null || true' EXIT
    trap 'exit 1' HUP INT TERM
    pg_dump --lock-wait-timeout=30000 -h db -U xushi -Fc xushi_schedule -f "$pending/database.dump" || exit 1
    pg_restore --list "$pending/database.dump" > /dev/null || exit 1
    # Profiles, screenshots and query caches are regenerable and may be actively written.
    # Keep encrypted configs and persisted keys; don't include plaintext deployment .env.
    if test -d "$source_data" && test -n "$(find "$source_data" -type f -print -quit)"; then
    tar -czf "$pending/data.tar.gz" --exclude='*/managed-browser-profile' \
        --exclude='*/browser-profile' --exclude='*/cache.sqlite3*' \
        --exclude='*/login-page.png' --exclude='*.tmp' --exclude='.env*' -C "$source_data" . || exit 1
    else
        echo "WARNING: persistent data unavailable; database backup retained" >&2
        printf '%s\n' 'Persistent data mount unavailable or empty' > "$pending/data-unavailable.txt"
        tar -czf "$pending/data.tar.gz" -C "$pending" data-unavailable.txt || exit 1
    fi
    tar -tzf "$pending/data.tar.gz" > "$pending/archive.list" || exit 1
    grep -q '[^/]$' "$pending/archive.list" || { echo "backup archive contains no files" >&2; exit 1; }
    rm "$pending/archive.list"
    (cd "$pending" && sha256sum database.dump data.tar.gz > SHA256SUMS) || exit 1
    date -u +%FT%TZ > "$pending/completed_at" || exit 1
    mv "$pending" "$bundle" || exit 1
    trap - EXIT HUP INT TERM
    echo "backup ok: $bundle"
    # Only prune this script's complete bundles, preserving legacy dumps and pending work.
    find "$root" -mindepth 1 -maxdepth 1 -type d -name 'xushi_bundle_*Z' -mtime +14 \
        -exec sh -c 'for dir do find "$dir" -type f -delete; rmdir "$dir"; done' sh {} +
)

while :; do
    if backup_once; then
        [ "${BACKUP_ONCE:-0}" = 1 ] && exit 0
        sleep 86400
    else
        echo "backup failed; retry in 300 seconds" >&2
        [ "${BACKUP_ONCE:-0}" = 1 ] && exit 1
        sleep 300
    fi
done
