FROM postgres:17-alpine

ENV BACKUP_DIR=/backups \
    BACKUP_INTERVAL_SECONDS=86400 \
    BACKUP_RETENTION_DAYS=14 \
    BACKUP_MAX_AGE_SECONDS=90000

COPY --chmod=755 ops/postgres-backup/backup.sh /usr/local/bin/postgres-backup
COPY --chmod=755 ops/postgres-backup/healthcheck.sh /usr/local/bin/postgres-backup-healthcheck

RUN mkdir -p /backups && chown postgres:postgres /backups

USER postgres

HEALTHCHECK --interval=1m --timeout=5s --start-period=2m --retries=3 \
    CMD ["/usr/local/bin/postgres-backup-healthcheck"]

ENTRYPOINT ["/usr/local/bin/postgres-backup"]
