# Privacy and data minimization

The current build transmits microphone audio only after an intentional PTT press
and stops capture before sending `ptt.end`. There is no open-microphone mode,
local VAD, background transcription, or continuous microphone analysis.

The client continuously sends decoded own-cockpit DCS-BIOS outputs to the cloud
as `telemetry.catalog`, `telemetry.snapshot`, and `telemetry.delta` messages.
Only own-aircraft module outputs and CommonData passive DCS-BIOS exports are
accepted. No Lua, filesystem, enemy, world, target, or hidden mission data
crosses this interface. The client never writes to DCS. Only controls whose
values have changed are retransmitted after the initial snapshot.

The backend holds the raw decoded telemetry values bounded in the authenticated
connection's in-process session memory. It does not persist, log, or archive
full cockpit snapshots or raw telemetry time series. When the session
disconnects the in-memory telemetry state is discarded.

The backend uses the telemetry stream to run normalization, phase detection,
deterministic rules, checklists, event management, and speech policy entirely in
the cloud. No cross-wire `tool.request` is issued to the client; aircraft state
is read backend-internally from the session-memory store.

Control identities are stable symbolic tuples (module, identifier, output type,
output index), not numeric DCS-BIOS addresses or memory offsets.

The gateway keeps a bounded in-memory list of audio byte/chunk receipts for
diagnostics; it does not persist or log audio payloads.

Proactive events are generated backend-side from deterministic rule transitions.
Eligible events contain only a rule ID, severity, own-aircraft identifier,
flight phase when known, a short deterministic message, and bounded rule data.
No raw telemetry values or complete state are included.

Persistent cloud records are limited to:

- user identity, salted password hashes, and hashed refresh credentials;
- explicit pilot memories and allowlisted aircraft preferences (written only on
  explicit pilot request);
- semantic flight session timestamps and an optional own-aircraft identifier —
  no raw telemetry, cockpit snapshot, audio, transcripts, mission state, or
  enemy/world state;
- versioned end-of-flight rule summaries: a random summary UUID, own-aircraft
  name, allowlisted rule IDs, and bounded activation counts only.

All persistent records are isolated by authenticated user. A pilot can
explicitly forget an individual memory and revoke a refresh credential; broader
account export/deletion and conversation-retention controls remain requirements
before real customer traffic is accepted.

The client contains only DCS Copilot service credentials. It never reads or
stores an OpenAI credential. Account memory, deterministic habit queries, and
all AI inference run inside the cloud process and are not accessible via the
client-facing protocol.
