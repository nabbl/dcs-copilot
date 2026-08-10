# CapRover deployment

The backend and its PostgreSQL backup worker are published to GHCR and deployed
to CapRover by `.github/workflows/backend.yml`. PostgreSQL itself is a separate
persistent CapRover One-Click App and is never exposed publicly.

## One-time CapRover setup

Create three CapRover apps:

| App | Persistent | Public | Configuration |
| --- | --- | --- | --- |
| `dcs-copilot-postgres` | Yes | No | PostgreSQL 17 One-Click App |
| `dcs-copilot-api` | No | Yes | Container port `8000`, WebSocket support, HTTPS, Force HTTPS |
| `dcs-copilot-postgres-backup` | Yes | No | Persistent directory `/backups` |

The names are examples; the workflow accepts any names through GitHub secrets.
Configure the CapRover Cluster registry settings with a GHCR username and a
token that can read the repository packages so CapRover can pull private
images.

Set these environment variables on `dcs-copilot-api`:

```text
CLOUD_HOST=0.0.0.0
CLOUD_PORT=8000
DCS_COPILOT_DEV_TOKEN=
DCS_COPILOT_DATABASE_URL=postgresql+asyncpg://dcs_copilot:REPLACE_ME@srv-captain--dcs-copilot-postgres:5432/dcs_copilot
DCS_COPILOT_AUTH_SIGNING_KEY=REPLACE_ME
OPENAI_API_KEY=REPLACE_ME
```

The model and timeout variables from `.env.example` are optional. Do not copy a
populated `.env` file into an image.

Set these environment variables on `dcs-copilot-postgres-backup`, using the
same database credentials as the PostgreSQL app:

```text
PGHOST=srv-captain--dcs-copilot-postgres
PGPORT=5432
PGDATABASE=dcs_copilot
PGUSER=dcs_copilot
PGPASSWORD=REPLACE_ME
BACKUP_INTERVAL_SECONDS=86400
BACKUP_RETENTION_DAYS=14
BACKUP_MAX_AGE_SECONDS=90000
```

Add a label-based persistent directory for the backup app with container path
`/backups`. The worker creates an immediate custom-format `pg_dump`, validates
it with `pg_restore --list`, then repeats daily. Incomplete dumps retain a
`.partial` suffix and are never promoted. Dumps older than 14 days are removed.
The container becomes unhealthy when the latest successful backup is more than
25 hours old.

The dump volume protects against database corruption and accidental changes,
but it remains on the CapRover server. Include its Docker volume in encrypted
off-server snapshots or sync it to object storage so a server loss does not
remove both the database and its backups.

## GitHub production configuration

Create a `production` environment and add:

| Type | Name | Value |
| --- | --- | --- |
| Secret | `CAPROVER_SERVER` | `https://captain.example.com` |
| Secret | `CAPROVER_BACKEND_APP` | `dcs-copilot-api` |
| Secret | `CAPROVER_BACKEND_APP_TOKEN` | Backend app token from CapRover |
| Secret | `CAPROVER_BACKUP_APP` | `dcs-copilot-postgres-backup` |
| Secret | `CAPROVER_BACKUP_APP_TOKEN` | Backup app token from CapRover |
| Variable | `DCS_COPILOT_HEALTH_URL` | `https://api.example.com/healthz` |

The workflow tests the cloud and shared packages, publishes commit-addressed
backend and backup images plus moving `main` tags, deploys the immutable commit
tags, and retries the public health endpoint for up to 150 seconds. Deployment
only passes when `/healthz` reports both `status=ok` and `ai_inference=true`.

For the Windows installer workflow, set the existing repository variable
`DCS_COPILOT_SERVICE_URL` to the matching
`wss://api.example.com/v1/realtime` URL.

## Restore a dump

Practice this before production. Put the API in maintenance mode, create a
fresh dump, and identify the CapRover overlay network and backup volume:

```bash
docker network ls
docker volume ls | grep postgres-backup
```

Then run PostgreSQL 17 tooling on the CapRover host, substituting the actual
network, volume, password, service hostname, and dump filename:

```bash
docker run --rm \
  --network captain-overlay-network \
  --volume captain--dcs-copilot-postgres-backups:/backups:ro \
  --env PGPASSWORD=REPLACE_ME \
  postgres:17-alpine \
  pg_restore --clean --if-exists --no-owner --no-privileges \
    --host srv-captain--dcs-copilot-postgres \
    --username dcs_copilot \
    --dbname dcs_copilot \
    /backups/dcs_copilot-YYYYMMDDTHHMMSSZ.dump
```

Restart the API and confirm its public `/healthz` endpoint after the restore.
