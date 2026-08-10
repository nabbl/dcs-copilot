# CapRover deployment

The backend is published to GHCR and deployed to CapRover by
`.github/workflows/backend.yml`. PostgreSQL is a separate persistent CapRover
One-Click App and is never exposed publicly.

## One-time CapRover setup

Create two CapRover apps:

| App | Persistent | Public | Configuration |
| --- | --- | --- | --- |
| `dcs-copilot-postgres` | Yes | No | PostgreSQL 17 One-Click App |
| `dcs-copilot-api` | No | Yes | Container port `8000`, WebSocket support, HTTPS, Force HTTPS |

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

## GitHub production configuration

Create a `production` environment and add:

| Type | Name | Value |
| --- | --- | --- |
| Secret | `CAPROVER_SERVER` | `https://captain.example.com` |
| Secret | `CAPROVER_BACKEND_APP` | `dcs-copilot-api` |
| Secret | `CAPROVER_BACKEND_APP_TOKEN` | Backend app token from CapRover |
| Variable | `DCS_COPILOT_HEALTH_URL` | `https://api.example.com/healthz` |

The workflow tests the cloud and shared packages, publishes a commit-addressed
backend image plus a moving `main` tag, deploys the immutable commit tag, and
retries the public health endpoint for up to 150 seconds. Deployment only
passes when `/healthz` reports both `status=ok` and `ai_inference=true`.

For the Windows installer workflow, set the existing repository variable
`DCS_COPILOT_SERVICE_URL` to the matching
`wss://api.example.com/v1/realtime` URL.
