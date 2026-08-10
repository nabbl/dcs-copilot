# DCS Copilot cloud

Milestones 3 and 4 run the PTT voice and aircraft-tool cascade in the cloud:

```text
bounded PCM turn -> OpenAI STT -> Pipecat context -> OpenAI Responses
                 -> streaming OpenAI TTS PCM -> client
```

When the LLM needs live state, Pipecat pauses the response while the gateway
sends one versioned, narrow `tool.request` to the client. The correlated
`tool.result` resumes the LLM and TTS stream. Tool calls time out and fail closed
on disconnect; no raw telemetry stream enters the cloud.

STT, LLM, and TTS are selected through provider interfaces and environment
configuration. The OpenAI key exists only in the cloud process. Copy
`.env.example` to `.env`, add a development API key, then run from this
directory with `uv run dcs-copilot-cloud`.

The gateway remains usable without a key for protocol diagnostics, but voice
turns fail closed with `voice_pipeline_failed` and `/healthz` reports
`ai_inference: false`.
