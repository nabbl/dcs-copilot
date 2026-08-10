# Privacy and data minimization

The current Milestone 7 build transmits microphone audio only after an
intentional PTT press and stops capture before sending `ptt.end`. There is no
open-microphone mode, local VAD, background transcription, or continuous
microphone analysis.

The client does not upload raw DCS-BIOS frames or periodic complete cockpit
snapshots. DCS state, normalization, phases, history, and rules remain local.
The gateway receives session metadata, PTT control messages, intentional PCM
audio, semantic tool results requested for the active conversation, and
speech-policy-approved semantic events.

The four client tools are versioned, read-only, and allowlisted. State reads
require explicit safe fields; issue, phase, and recent-event results are bounded.
The interface cannot access raw DCS-BIOS, complete cockpit snapshots, files,
shell commands, Lua, cockpit controls, enemy/world state, or arbitrary DCS data.
The gateway keeps a bounded in-memory list of audio byte/chunk receipts for
diagnostics; it does not persist or log audio payloads.

Proactive publication is independently minimized by the local speech policy.
Eligible events contain only a rule ID, severity, own-aircraft identifier,
flight phase when known, a short deterministic message, and bounded rule data.
Raw telemetry and complete state are never attached. Events remain in bounded
client memory when the cloud is unavailable and are not replayed on reconnect.

Milestone 6 added cloud persistence for user identity, salted password hashes,
hashed refresh credentials, explicit memories/preferences, and semantic flight
session timestamps plus an optional aircraft name. These records are isolated
by user. Flight history deliberately excludes raw telemetry, rule-event totals,
audio, transcripts, mission data, and enemy/world state. A pilot can explicitly
forget an individual memory and revoke a refresh credential; broader account
export/deletion and conversation-retention controls remain requirements before
real customer traffic is accepted.

Milestone 7 additionally uploads one semantic summary at the end of a flight.
It contains only a random summary ID, own-aircraft name, allowlisted local rule
IDs, and bounded activation counts. Coverage is explicit: a rule is absent when
its required telemetry was never usable. Summaries never contain raw values,
cockpit snapshots, event messages, timeseries, audio, transcripts, mission
state, or enemy/world state. They are isolated by signed-in user and accepted
idempotently.

The client contains only DCS Copilot service credentials. It never reads or
stores an OpenAI credential. Account memory and deterministic habit queries run
inside the cloud and are not copied into the local aircraft-tool protocol.
