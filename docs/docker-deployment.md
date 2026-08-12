# Docker deployment

Docker Compose runs the cloud/Pipecat backend and PostgreSQL. The Windows
client remains a native application because it needs Windows global keyboard
input, the credential vault, DCS process focus, host audio devices, and local
DCS-BIOS multicast.

Protocol version 2 is the only supported version. A v1 client cannot connect to
this gateway. The client and cloud must be upgraded together.

## Start the backend

Install Docker Desktop or Docker Engine with the Compose plugin, then run from
the repository root:

```bash
cp .env.example .env
openssl rand -hex 32  # use this for DCS_COPILOT_AUTH_SIGNING_KEY
openssl rand -hex 24  # use this for POSTGRES_PASSWORD
```

Edit `.env` and set the two generated secrets plus `OPENAI_API_KEY`. Then build
and start the services:

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8000/healthz
```

The health response should contain `"status":"ok"` and
`"ai_inference":true`. Follow logs with `docker compose logs -f backend` and
stop the deployment with `docker compose down`. PostgreSQL data is retained in
the `postgres-data` named volume. `docker compose down -v` also deletes that
database and should only be used when a full reset is intended.

Compose deliberately disables `DCS_COPILOT_DEV_TOKEN`. Users authenticate via
the registration/login API and the Windows desktop client stores its refresh
credential in the Windows credential vault.

## Connect the Windows client

For Docker Desktop on the same Windows PC, use:

```text
ws://127.0.0.1:8000/v2/realtime
```

Enter that URL in the desktop client's service URL setting, or bake it into an
installer:

```powershell
./packaging/windows/build.ps1 -Version 0.1.0 `
  -ServiceUrl "ws://127.0.0.1:8000/v2/realtime"
```

For a backend on another computer or a public server, terminate TLS in a
reverse proxy/load balancer that supports WebSocket upgrades and expose the
service as `wss://your-domain.example/v2/realtime`. The client intentionally
rejects unencrypted `ws://` connections to non-loopback hosts. Do not expose
PostgreSQL; only the backend port is published by Compose.

Build a remote-client installer with the public URL:

```powershell
./packaging/windows/build.ps1 -Version 0.1.0 `
  -ServiceUrl "wss://your-domain.example/v2/realtime"
```

## Environment variables

Required values live in the root `.env` file and are passed only to the
backend/database containers:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Server-side STT (gpt-transcribe), LLM (gpt-5.6-luna), and TTS access |
| `DCS_COPILOT_AUTH_SIGNING_KEY` | Signs short-lived account access tokens |
| `POSTGRES_PASSWORD` | Password for the private Compose PostgreSQL service |

`.env.example` also documents the host port, model selection, token lifetimes,
and logging overrides. Keep `.env` out of source control and use the deployment
platform's secret store for production.

Back up the PostgreSQL volume before upgrades. This application currently
creates missing tables at startup; production schema migrations, TLS,
authentication rate limiting, monitoring, and secret rotation remain release
requirements.
