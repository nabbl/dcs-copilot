#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

backup_dir=${BACKUP_DIR:-/backups}
interval_seconds=${BACKUP_INTERVAL_SECONDS:-86400}
retention_days=${BACKUP_RETENTION_DAYS:-14}

case "$interval_seconds" in
    ''|*[!0-9]*) echo "BACKUP_INTERVAL_SECONDS must be a positive integer" >&2; exit 2 ;;
esac
case "$retention_days" in
    ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac
if [ "$interval_seconds" -lt 1 ]; then
    echo "BACKUP_INTERVAL_SECONDS must be greater than zero" >&2
    exit 2
fi

mkdir -p "$backup_dir"
umask 077

run_backup() {
    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    final_path="$backup_dir/${PGDATABASE}-${timestamp}.dump"
    partial_path="${final_path}.partial"
    success_path="$backup_dir/.last-success"
    success_partial="${success_path}.partial"

    rm -f "$partial_path" "$success_partial"
    echo "Creating PostgreSQL backup $final_path"
    pg_dump --format=custom --no-owner --no-privileges --file="$partial_path"
    pg_restore --list "$partial_path" >/dev/null
    mv "$partial_path" "$final_path"

    date -u +%s >"$success_partial"
    mv "$success_partial" "$success_path"
    find "$backup_dir" -type f -name "${PGDATABASE}-*.dump" \
        -mtime "+${retention_days}" -delete
    echo "PostgreSQL backup completed"
}

shutdown() {
    echo "PostgreSQL backup service stopping"
    exit 0
}
trap shutdown INT TERM

while :; do
    run_backup
    sleep "$interval_seconds" &
    wait "$!"
done
