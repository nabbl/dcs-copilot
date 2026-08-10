# DCS Copilot cloud

Milestones 3 through 7 run the PTT voice, aircraft-tool, proactive-speech,
account-memory, and deterministic habit services in the cloud:

```text
bounded PCM turn -> OpenAI STT -> Pipecat context -> OpenAI Responses
                 -> streaming OpenAI TTS PCM -> client
```

When the LLM needs live state, Pipecat pauses the response while the gateway
sends one versioned, narrow `tool.request` to the client. The correlated
`tool.result` resumes the LLM and TTS stream. Tool calls time out and fail closed
on disconnect; no raw telemetry stream enters the cloud.

Milestone 5 accepts validated `event.raised` and `event.resolved` controls. The
gateway speaks the deterministic short event message through the configured
cloud TTS provider, streams PCM immediately, suppresses advisories while another
turn is active, and lets PTT or event resolution cancel playback.

Milestone 6 adds account registration/login, signed 15-minute access tokens,
rotating refresh credentials stored only as hashes, and an async persistence
layer. SQLite is supported for development; production uses PostgreSQL through
`asyncpg`. One authenticated user owns each memory, preference, and flight
session. Pipecat exposes narrow cloud tools for explicit remember/forget/recall,
chatter preferences, and bounded flight history. These are separate from the
four client-side aircraft tools.

Milestone 7 accepts versioned semantic end-of-flight summaries only from signed
user sessions. Storage is idempotent and user-isolated. The allowlisted
`get_pilot_habits` cloud tool calculates coverage-aware counts and returns the
exact sentence the LLM should speak. It does not infer habits from memories or
generic flight-session history.

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
