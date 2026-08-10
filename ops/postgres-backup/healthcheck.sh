#!/bin/sh
set -eu

backup_dir=${BACKUP_DIR:-/backups}
max_age_seconds=${BACKUP_MAX_AGE_SECONDS:-90000}
success_path="$backup_dir/.last-success"

case "$max_age_seconds" in
    ''|*[!0-9]*) exit 2 ;;
esac
[ "$max_age_seconds" -gt 0 ] || exit 2
[ -r "$success_path" ] || exit 1

last_success=$(cat "$success_path")
case "$last_success" in
    ''|*[!0-9]*) exit 1 ;;
esac

now=$(date -u +%s)
age=$((now - last_success))
[ "$age" -ge 0 ] && [ "$age" -le "$max_age_seconds" ]
