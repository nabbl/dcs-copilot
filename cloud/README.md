# DCS Copilot cloud

The backend is the authoritative semantic engine. It receives the client's
continuous decoded own-cockpit telemetry stream, holds raw values bounded in
authenticated session memory, and owns all normalization, phase detection,
deterministic rules, checklists, event management, speech policy, habit
statistics, and MARA tool execution. It also runs the PTT voice pipeline and
account services:

```text
telemetry catalog/snapshot/delta -> AircraftStateStore
                                     |- normalization
                                     |- phase detection
                                     |- deterministic rules
                                     |- checklists
                                     |- event management
                                     `- speech policy

bounded PTT turn -> gpt-transcribe STT -> Pipecat context
                  -> gpt-5.6-luna Responses LLM
                  -> streaming cloud TTS PCM -> client
```

Raw telemetry values are held only in the authenticated connection's in-process
session memory. They are never persisted, logged as complete snapshots, or
stored as raw time series. Semantic account, history, and habit records may
persist as documented in `docs/accounts.md`.

MARA's aircraft tools (`get_aircraft_state`, `get_active_issues`,
`get_recent_events`, `get_flight_phase`, `get_checklist_status`,
`get_missing_checklist_items`, and guided-checklist controls) execute
backend-internally against the session-memory `AircraftStateStore`. No
`tool.request` message is sent to the client. Unavailable values remain
unavailable; `get_active_issues` reports `coverage` so an empty list never
implies an all-clear.

Speech policy runs backend-side. When a deterministic rule activates, the
backend synthesises the rule's short message through the configured cloud TTS
provider and streams `AUDIO_OUTPUT` directly — without asking an LLM to invent
safety phrasing. Warnings may replace an active voice response; advisories do
not.

Checklist definitions, normalization mappings, and rule parameters are
backend-only artefacts. Changes to them require only a backend deployment when
their required DCS-BIOS controls are already exported by the client.

Account registration/login, signed 15-minute access tokens, rotating refresh
credentials stored only as hashes, and an async persistence layer are
implemented. SQLite is supported for development; production uses PostgreSQL
through `asyncpg`. Pipecat exposes cloud account tools for explicit
remember/forget/recall, chatter preferences, and bounded flight history. These
are backend-internal functions and never produce client-facing `tool.request`
messages.

The backend `FlightStatsManager` observes the same deterministic rule
transitions as live monitoring and produces coverage-aware per-flight rule
summaries scoped to the authenticated user. `get_pilot_habits` calculates
observed-flight counts and returns the exact sentence the LLM should speak; the
LLM is required to repeat it and forbidden from deriving counts from memory or
generic flight history.

STT, LLM, and TTS are selected through provider interfaces and environment
configuration. The OpenAI key exists only in the cloud process. Copy
`.env.example` to `.env`, add a development API key, then run from this
directory with `uv run dcs-copilot-cloud`.

Set `DCS_COPILOT_AUTH_SIGNING_KEY` to a strong deployment secret and
`DCS_COPILOT_DATABASE_URL` to the PostgreSQL URL. Set
`DCS_COPILOT_DEV_TOKEN=` outside loopback development so the placeholder-token
escape hatch is disabled. See [`docs/accounts.md`](../docs/accounts.md) for the
HTTP auth flow.

The gateway remains usable without a key for protocol diagnostics, but voice
turns fail closed with `voice_pipeline_failed` and `/healthz` reports
`ai_inference: false`.
