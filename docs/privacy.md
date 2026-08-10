# Privacy and data minimization

The current Milestone 6 build transmits microphone audio only after an
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

Milestone 6 adds cloud persistence for user identity, salted password hashes,
hashed refresh credentials, explicit memories/preferences, and semantic flight
session timestamps plus an optional aircraft name. These records are isolated
by user. Flight history deliberately excludes raw telemetry, rule-event totals,
audio, transcripts, mission data, and enemy/world state. A pilot can explicitly
forget an individual memory and revoke a refresh credential; broader account
export/deletion and conversation-retention controls remain requirements before
real customer traffic is accepted.

The client contains only DCS Copilot service credentials. It never reads or
stores an OpenAI credential. Account memory is queried inside the cloud and is
not copied into the local aircraft-tool protocol. No deterministic habit
statistics are uploaded in Milestone 6.
