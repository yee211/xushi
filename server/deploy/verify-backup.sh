#!/bin/sh
# Restores only into a newly created scratch database, never the application DB.
set -eu
umask 077
bundle=${1:?usage: verify-backup.sh /backups/xushi_bundle_TIMESTAMP}
test -d "$bundle"
(cd "$bundle" && sha256sum -c SHA256SUMS)
tar -tzf "$bundle/data.tar.gz" > /dev/null
scratch="xushi_restore_check_$(date -u +%Y%m%d%H%M%S)_$$"
created=0
cleanup() {
    if [ "$created" = 1 ]; then
        dropdb -h db -U xushi --maintenance-db=xushi_schedule "$scratch"
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
createdb -h db -U xushi --maintenance-db=xushi_schedule "$scratch"
created=1
pg_restore -h db -U xushi --exit-on-error --no-owner --no-privileges -d "$scratch" "$bundle/database.dump"
tables=$(psql -h db -U xushi -d "$scratch" -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('users','schedules','courses')")
test "$tables" = 3
echo "backup restore verification passed"
