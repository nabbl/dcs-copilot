# DCS Copilot thin client

The customer-side read-only DCS telemetry and audio peripheral. It retains
aircraft normalization and deterministic safety logic locally, captures PCM
only while PTT is held, and connects to the DCS Copilot service through the
shared versioned protocol. It contains no AI model or provider credential.
It also executes the four Milestone 4 aircraft tools locally against normalized
state, deterministic rules, bounded history, and flight phase. Tool calls are
read-only, allowlisted, and never expose raw or arbitrary DCS access.
Deterministic rule transitions also feed a bounded local `EventManager`.
`COPILOT_SPEECH_MODE` selects `MINIMAL`, `NORMAL`, or `COACH`; the policy sends
only eligible semantic events to cloud TTS and never uploads a cockpit snapshot.
There is intentionally no local warning-audio pack in this build.
