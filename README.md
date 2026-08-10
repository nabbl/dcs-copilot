# DCS Copilot

DCS Copilot is a commercial thin-client/cloud service in development. The
current build implements the reset Milestones 1 through 7:

- passive local DCS-BIOS ingestion, normalized Hornet state, phases and rules;
- replay, diagnostics and resource instrumentation;
- a versioned client/cloud protocol;
- a FastAPI gateway with signed account authentication and a local dev-token
  escape hatch;
- F13 PTT-scoped PCM capture, binary audio transport and playback plumbing;
- a persistent cloud Pipecat cascade with configurable OpenAI STT, Responses
  LLM, streaming TTS, and PTT barge-in cancellation;
- four versioned, allowlisted read-only aircraft tools evaluated against local
  normalized state, deterministic issues, history, and flight phase;
- deterministic semantic event management, local `MINIMAL`/`NORMAL`/`COACH`
  speech policy, and cloud-streamed proactive warning audio.
- cloud user accounts with short-lived device-bound access tokens, rotating
  refresh credentials, PostgreSQL/SQLite persistence, explicit pilot memories,
  aircraft preferences, and semantic flight-session history.
- coverage-aware end-of-flight rule summaries and deterministic, user-isolated
  habit statistics that never ask an LLM to calculate a count.

There is no Pipecat, STT, LLM, TTS, OpenAI key, or neural model on the customer
client. All AI inference and its dependencies are isolated in `cloud/`.

The customer build is a native Windows desktop application with account login,
Saved Games discovery, DCS-BIOS installation/repair, `Export.lua` setup,
client settings, health status, and runtime controls. Refresh credentials are
kept in the operating-system credential vault; short-lived access tokens are
renewed before each realtime connection.

```text
client/   customer-side DCS telemetry/audio peripheral
cloud/    session gateway, Pipecat, and provider-isolated AI cascade
shared/   standard-library protocol envelopes
docs/     architecture, protocol, privacy and validation decisions
```

## Local development

Install `uv`. Copy `cloud/.env.example` to `cloud/.env`, set a development
`OPENAI_API_KEY` there, and start the gateway from the cloud directory. The key
must never be placed in `client/.env` or on a customer gaming PC.

Start the gateway:

```bash
cd cloud
uv run dcs-copilot-cloud
```

In another terminal, copy `client/.env.example` to `client/.env`, optionally set
`DCS_BIOS_PATH` to the separately installed DCS-BIOS directory, then inspect
connectivity and run the client:

```bash
cd client
uv run dcs-copilot status --wait 1
uv run dcs-copilot run
```

To run the desktop shell during development:

```bash
cd client
uv run dcs-copilot-desktop
```

On Windows, `run` listens globally for F13 while DCS has focus. For POSIX local
development, `uv run dcs-copilot run --stdin-ptt` uses Enter to start and end a
turn. The microphone is not opened before PTT and release ends the turn without
VAD. The cloud transcribes the bounded turn, generates a deliberately concise
reply, and begins returning 24 kHz PCM while TTS is still streaming.

Questions about live cockpit state cause the cloud LLM to request only the
needed semantic data over the existing WebSocket; raw DCS-BIOS frames and full
cockpit snapshots remain local.

Explicit account memories are different from live aircraft state. A request
such as “Remember Hornet Bingo is 3500” invokes an allowlisted cloud memory
tool. A later authenticated session retrieves that fact from the account
database. Habit questions use separately uploaded, allowlisted semantic rule
counts. The cloud calculates the exact coverage-aware statement before the LLM
sees it; memories and generic flight history are never used to infer habits.

Proactive warnings use the same cloud TTS path. If the cloud is unavailable,
local monitoring and event history continue, but this build does not promise
offline warning audio.

Other development commands remain available:

```bash
uv run dcs-copilot watch
uv run dcs-copilot replay client/tests/fixtures/replay/airborne-alerts.jsonl
uv run dcs-copilot benchmark
uv run --all-packages pytest -q
uvx ruff check .
uv run --with mypy mypy client/dcs_copilot shared/dcs_copilot_protocol cloud/dcs_copilot_cloud
```

See [the architecture decision](docs/architecture.md), [wire
protocol](docs/protocol.md), [privacy boundary](docs/privacy.md), [client
performance methodology](docs/client-performance.md), [accounts and
memory](docs/accounts.md), [deterministic habits](docs/habits.md), and [multiplayer validation
matrix](docs/multiplayer-validation.md).

See [the Windows client and release guide](docs/windows-client.md) for local
packaging, the installer flow, code-signing requirements, and first-run setup.
