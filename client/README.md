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

Milestone 6 keeps account data off the gaming PC. The client sends its
service-issued, short-lived access token and a stable device identifier during
the WebSocket handshake. It reports only a versioned aircraft identifier for
the cloud flight-session record; no cockpit snapshot or telemetry accompanies
that metadata. Login, refresh, memory, and database logic remain cloud-side.

Milestone 7 adds local `FlightStatsManager` aggregation over the same
deterministic rules. On flight end it sends only an allowlisted rule/count map
with explicit telemetry coverage. Unavailable rules are omitted, never guessed
clear. Summaries remain bounded and pending until a correlated cloud ack; no
raw or complete normalized state is uploaded.
