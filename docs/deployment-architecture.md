# MARA deployment architecture

## Repository audit

The repository has three Python workspace packages. `client/` is the native
PySide6 Windows application and DCS host integration. `cloud/` is the single
FastAPI backend implementation. `shared/` contains the versioned control/media
protocol and the application/API version constants.

The client already is the narrow host bridge needed by a remote topology. It
owns DCS-BIOS UDP multicast and metadata, Saved Games and `Export.lua` setup,
loopback indication discovery, controller/keyboard PTT, microphone capture,
speaker playback, and telemetry publication. These responsibilities cannot be
moved to a remote server. No additional host-bridge process is needed.

The backend exposes HTTP account operations and `/v2/realtime` WebSocket media
and telemetry. It owns SQLite/PostgreSQL persistence, authentication, Pipecat,
OpenAI STT/LLM, local Kokoro or OpenAI TTS, normalized aircraft state, Coach
rules/events/checklists, memories, and habits. The same `create_app` factory is
used by source development, PyInstaller, Docker, hosted deployment, localhost,
and LAN deployment.

Before this change the frontend stored one `cloud_url`, always required an
account UI, and never launched a backend. The backend offered `/healthz` only,
read OpenAI credentials directly from the environment, used source/CWD-relative
SQLite defaults, and was shipped only as a container. PyInstaller and Inno
Setup existed for the client, while GitHub Actions produced only the client
installer. There is no updater. Logging used Uvicorn output without a bounded
packaged log. Hosted authentication and Docker/CapRover deployment already
existed and are retained.

## Accepted topology

```text
Local (default)

DCS -> Windows client/host bridge -> ws://127.0.0.1:47100/v2/realtime
                                      MaraBackend.exe
                                      |- FastAPI / Coach / state / SQLite
                                      |- Pipecat / OpenAI STT+LLM
                                      `- local Kokoro TTS
```

```text
Remote

DCS -> Windows client/host bridge -> LAN or HTTPS backend
                                      same FastAPI application
                                      same WebSocket protocol
```

The frontend always uses HTTP for health/handshake and WebSocket for the live
session. Localhost is not an in-process special case. `backend.mode=local`
authorizes lifecycle management; `backend.mode=remote` never launches or stops
a local process. The client distinguishes an already-running backend from its
own child and only terminates the latter.

## Configuration and migration

Non-secret desktop configuration is schema version 2:

```json
{
  "schema_version": 2,
  "backend": {
    "mode": "local",
    "url": "http://127.0.0.1:47100"
  }
}
```

Fresh installations use local mode. A legacy config containing `cloud_url` is
migrated to remote mode with the URL preserved. Unknown/malformed optional
fields use safe defaults. `%LOCALAPPDATA%\DCS Copilot\config.json` is read as a
legacy source; subsequent saves use `%LOCALAPPDATA%\MARA\config\mara.json`.

Mutable local data lives below `%LOCALAPPDATA%\MARA\{config,data,models,logs,runtime}`.
Installed executables are read-only. The local database is `data\mara.db` and
rotating backend logs are stored in `logs\backend.log`; child stdout/stderr is
captured separately in `logs\backend-process.log`.

## Credentials and providers

The credential abstraction has environment, OS-keyring, chained, and in-memory
test implementations. Packaged local installations store the OpenAI key as the
`openai-api-key` account in the `MARA Backend` Windows Credential Manager
service. It is never serialized in desktop/backend JSON, passed on a process
command line, logged, or sent to a remote backend. Hosted deployments retain
`OPENAI_API_KEY` through the environment adapter.

OpenAI remains the configured STT and LLM. Local mode defaults to Pipecat's
Kokoro ONNX TTS provider (`af_heart`), whose model and voices are resumed,
SHA-256 verified, and cached automatically on first local backend startup.
Hosted mode defaults to OpenAI TTS,
preserving the deployed behavior. Provider construction remains backend-only.

## Lifecycle, compatibility, and security

`GET /health` proves that the process accepts requests. `GET /ready` reports
database initialization and provider/component state. `GET /api/system/info`
reports `mara_version`, the separately versioned `api_version`, transport
protocol, deployment, capabilities, TTS provider, and credential presence—never
the credential.

The desktop probes system info with bounded timeouts and exact API-version
validation. Local startup uses readiness polling rather than sleeps, detects
startup exits, captures logs, supervises unexpected exits with two bounded
restarts, and exposes Test Connection and Restart Backend controls. Closing the
desktop gracefully terminates only a backend it launched, with forced kill as a
bounded fallback.

The backend defaults to `127.0.0.1`. A LAN bind is explicit. The standalone CLI
disables the development token and creates a private signing key when first
bound off-loopback. Public remote traffic requires TLS; unencrypted WebSocket
is accepted only on loopback or a private/link-local LAN. No firewall rule is
created. Hosted account authentication is unchanged.

## Packaging and hosted compatibility

`packaging/windows/build.ps1` now builds the windowed client, CLI, and
`MaraBackend.exe`, then produces:

- `MARA-Setup-<version>.exe` — combined normal installation;
- `MARA-Backend-<version>-windows-x64.zip` — standalone backend, example
  non-secret config, usage/security guide, and notices;
- `checksums.txt` — SHA-256 release checksums.

The Docker image explicitly selects `MARA_DEPLOYMENT=hosted`, continues to use
the same backend package and PostgreSQL settings, and now probes `/ready`.
Windows CI builds and smoke-tests the frozen backend before publishing
artifacts. Source development continues to support `uv run dcs-copilot-cloud`
and custom development ports without rebuilding executables.
