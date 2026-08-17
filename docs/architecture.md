# DCS Copilot architecture decision

Status: accepted for the commercial SaaS direction.

## Decision

DCS Copilot is split into three independently deployable components:

```text
dcs-copilot/
    client/   # customer gaming PC
    cloud/    # DCS Copilot operated service
    shared/   # versioned wire schemas only
```

The governing rule is: **the client is a generic DCS-BIOS reader and audio
transport; the backend is authoritative for normalization, reasoning, and
speech**.

The client owns DCS-BIOS ingestion, own-cockpit telemetry publishing, PTT
capture and playback, and the authenticated cloud connection. It does not
perform aircraft normalization, phase detection, rule evaluation, checklist
execution, event management, speech policy, or habit accounting. It contains no
OpenAI credential and runs no neural model.

The backend owns the entire semantic pipeline: receiving and holding the raw
decoded telemetry stream in bounded session memory, normalization, phase
detection, deterministic rules, checklists, semantic event management, speech
policy, habit statistics, and MARA tool execution. It also owns Pipecat, STT
(gpt-transcribe), Responses LLM (gpt-5.6-luna), and configured cloud TTS.

`shared` contains transport-neutral protocol schemas. It must not contain
business logic or force the client to install cloud dependencies. The transport
is an authenticated WebSocket; media and control abstractions must allow a later
move to WebRTC without redesigning the Copilot Brain.

## Runtime boundaries

```text
CUSTOMER GAMING PC                         DCS COPILOT CLOUD

DCS -> DCS-BIOS -> thin client            authenticated session gateway
                   |- telemetry catalog ----> AircraftStateStore
                   |- telemetry snapshot --->   |- normalization
                   |- telemetry deltas ---->    |- phase detection
                   |- PTT audio --------->      |- deterministic rules
                   |- response playback <-      |- checklists
                                                |- event management
                                                |- speech policy
                                                |- habit stats
                                                `- Pipecat / STT / LLM / TTS
```

Client-to-cloud data is limited to PTT audio, the own-cockpit telemetry stream
(catalog + initial snapshot + changed-value deltas), and bounded normalized
Coach observations containing ownship plus at most one selected lead and carrier.
The telemetry stream
is held bounded in authenticated session memory; it is never persisted or logged
as full snapshots or raw time series. Semantic account, history, and habit
records may persist as documented in `docs/accounts.md`.

Only own-aircraft modules and CommonData passive DCS-BIOS outputs are accepted
on the cockpit stream. The separate Coach stream is produced by the packaged
read-only `MARASpatial.lua` provider. It calls `LoGetWorldObjects()` only while
`LoIsObjectExportAllowed()` is true and emits only normalized ownship and the
selected Coach references—not a world-object dump. No filesystem, target,
sensor substitute, or hidden mission state is accepted. The client never writes
to DCS.

## Existing-code disposition

The existing repository was inspected before this decision.

Retain in the client:

- the incremental DCS-BIOS protocol parser and passive multicast client;
- generated-control registry loading and `_ACFT_NAME` aircraft detection;
- the telemetry publisher (catalog, snapshot, coalesced delta generation);
- PTT capture, audio transport, and playback;
- permission-gated DCS spatial acquisition and bounded normalized publishing;
- authenticated cloud connection and session lifecycle.

Remove from the client / move to backend:

- Pipecat and its local audio pipeline;
- Kokoro and downloaded voice models;
- Silero VAD and Smart Turn;
- Jarvis and local STT clients;
- the OpenAI Responses client and customer-side API-key configuration;
- aircraft normalization and `AircraftState` models;
- phase detection, rule engine, and Hornet rules;
- checklist engine and guided-checklist state;
- event manager and speech policy;
- `FlightStatsManager` and end-of-flight summaries;
- local conversational prompts and LLM tool registration.

DCS-BIOS remains an external installation. The product consumes its published
multicast protocol and generated control metadata; it does not copy, modify, or
silently redistribute DCS-BIOS.

## Client resource contract

The production client has no AI optional extra and no dependency on Pipecat,
OpenAI, CUDA, Torch, ONNX, local model files, or vector databases. With no PTT
activity it performs only socket-driven DCS ingestion and bounded telemetry
publishing. Microphone capture is off while PTT is released.

Release validation records process CPU time, resident memory, frame/update
throughput, queue bounds, and parser errors. The definitive performance
acceptance test must measure DCS frametime on Windows in a demanding rendered
mission; automated tests on a development machine cannot prove that requirement
by themselves.

## Safety and multiplayer boundary

The client is read-only. It does not send DCS-BIOS or DCS commands or modify
protected aircraft files. Its spatial provider may inspect world objects only
after `LoIsObjectExportAllowed()` returns true, solely to select a nearby
friendly formation lead and carrier. It does not export the complete collection
or use target/sensor APIs, mission state, or Tacview as a permission bypass.

Only own-aircraft cockpit outputs and the bounded normalized Coach observation
are forwarded. If world-object permission disappears, the client immediately
publishes the denied capability without references and the backend clears its
registry and stops dependent exercises. Compatibility and Integrity Check claims
require the live test matrix in `docs/multiplayer-validation.md`.

## Dependency and deployment policy

Each component has its own manifest and virtual environment boundary:

- `client/pyproject.toml`: the shared schema package plus narrowly justified
  WebSocket, PortAudio, and Windows hotkey dependencies; no cloud or AI stack;
- `cloud/pyproject.toml`: FastAPI/Uvicorn session gateway, Pipecat, and AI
  provider dependencies, never installed on customer machines;
- `shared/pyproject.toml`: standard-library-only protocol schemas.

The top-level project is orchestration and documentation only. Python remains
acceptable for the prototype client because the retained runtime is I/O-bound
and model-free. The versioned protocol must remain implementable by a future
Rust client.

## Protocol versioning and migration

Protocol version 2 is the current and only supported version. Version 1 is
unsupported. The client and cloud must be upgraded together; there is no
negotiation or fallback path.

Checklist definitions, normalization mappings, and rule parameters are
backend-only deployment artefacts when their required DCS-BIOS controls are
already exported by the client. Changes to those artefacts require only a
backend deployment, not a client update.

## Reset milestone sequence

1. **Thin DCS client (implemented):** retained telemetry parsing, control
   registry, replay, diagnostics, and client performance instrumentation.
2. **Client/cloud protocol (implemented):** versioned WebSocket at `/v2/realtime`,
   authenticated session, PTT capture, audio transport, telemetry
   catalog/snapshot/delta publishing.
3. **Cloud Pipecat voice (implemented):** gpt-transcribe STT, gpt-5.6-luna
   Responses LLM, streaming cloud TTS, and streamed response audio.
4. **Backend aircraft tools (implemented):** normalization, phase detection,
   rules, checklists, and event management execute in the cloud against the
   session-memory telemetry store; MARA queries them backend-internally.
5. **Proactive warnings (implemented):** backend-generated semantic events,
   speech policy, and interruptible cloud TTS advisories.
6. **Accounts and memory (implemented):** signed short-lived authentication,
   rotating refresh credentials, PostgreSQL/SQLite persistence, explicit
   memories, preferences, and semantic flight sessions.
7. **Habit learning (implemented):** backend deterministic, coverage-aware
   per-flight rule summaries and stored per-user habit calculations.
8. **Commercial foundation:** metering, entitlements, devices, rate limiting,
   and operations monitoring.

Milestones 3 through 7 preserve the original dependency boundary: Pipecat and
every AI provider exist only in the cloud package.

## Milestone 2 implementation contract

Protocol version 2 separates JSON control messages from binary media packets.
Every control envelope carries `protocol_version`, `message_id`, optional
`correlation_id`, a type, and a payload. Binary packets carry a stable magic,
version, media kind, sequence number, monotonic timestamp, and payload.

The client publishes a fresh epoch UUID on each new aircraft slot or reconnect,
followed by chunked `telemetry.catalog`, then chunked `telemetry.snapshot`, then
continuous `telemetry.delta` messages at 10–20 Hz. Deltas are coalesced over a
configurable flush interval; the publisher drops values that would overflow the
outbound queue and tracks the drop count for diagnostics. The backend accepts
only the `telemetry.*` message sequence; an out-of-order or duplicate-epoch
delta is rejected.

The gateway sends `hello`, authenticates a short-lived access token, starts one
session, accepts PCM only between `ptt.start` and `ptt.end`, and returns an
`utterance.received` receipt. PTT release is authoritative; neither side runs
VAD or turn inference. Plain `ws://` connections are accepted only for loopback
development.

## Milestone 3 voice contract

Each authenticated session owns one persistent Pipecat conversation pipeline.
PTT release injects the externally bounded 16 kHz PCM turn into cloud
gpt-transcribe STT; gpt-5.6-luna produces a concise response and cloud TTS
streams 24 kHz PCM back without waiting for the full utterance. Pressing PTT
while the assistant speaks stops local playback, sends `assistant.interrupt`,
cancels the active gateway task, and injects a Pipecat interruption frame.

The pipeline persists only for the current cockpit slot. When a new epoch
arrives in the telemetry stream, the backend interrupts and closes MARA's
pipeline, resets its session-memory telemetry state, and starts a fresh
conversation context while explicit account memories remain available.

## Milestone 4 backend aircraft-tool contract

MARA's allowlist is `get_aircraft_state`, `get_active_issues`,
`get_recent_events`, `get_flight_phase`, `get_checklist_status`,
`get_missing_checklist_items`, `start_guided_checklist`,
`get_next_checklist_item`, `confirm_checklist_item`, and
`stop_guided_checklist`, plus the Ground Operations v1 tools
`get_ground_ops_status` and `get_takeoff_readiness`, and the In-Flight
Operations v1 tools `get_flight_status` and `get_hornet_knowledge`. All tools
execute backend-internally against the session-memory `AircraftStateStore`; no
`tool.request` message is sent to the client. `get_aircraft_state` requires an
explicit normalized field list; raw
values, warning-light maps, and unrecognized fields are rejected. Results
preserve `AVAILABLE`, `STALE`, and `UNAVAILABLE` status; unavailable values are
returned as `null`, never inferred. `get_active_issues` reports `coverage` so
an empty list never silently implies an all-clear.

The thin client republishes its complete decoded DCS-BIOS snapshot every ten
seconds in addition to change deltas. This refresh contains no aircraft semantics;
it prevents stable cockpit controls from aging past the cloud's thirty-second
freshness window while preserving the cloud as the normalization authority.

Ground-operations readiness is separate from active rule violations. A takeoff
readiness result is `READY` only when every required current-state and operation
context gate is positively verified. Known wrong values produce `BLOCKED`;
unavailable telemetry or unknown land-versus-carrier context produce `UNKNOWN`.
Land-runway alignment is never inferred from cockpit-only
telemetry. The launch-bar/carrier sequence is the only positive alignment signal
in the first slice.

## Milestone 5 proactive-speech contract

The backend `EventManager` converts rule activations, resolutions, and
telemetry disablement into versioned semantic events with stable event IDs. It
retains a bounded history.

Speech policy is enforced by the backend. `MINIMAL` permits only critical
activations; `NORMAL` permits warnings plus explicitly relevant advisories;
`COACH` permits all cooldown-eligible severities. The backend synthesises the
deterministic short rule message through cloud TTS rather than asking an LLM to
invent safety phrasing. Warnings can replace an active cloud response;
advisories do not. PTT and a proactive event's own resolution cancel active
proactive speech. Events are not replayed after a disconnect reconnect.

## Milestone 6 accounts-and-memory contract

The cloud authenticates email/password accounts and issues device-bound,
short-lived signed access tokens plus rotating opaque refresh credentials.
Passwords use salted scrypt; only refresh-token hashes are stored.

Pipecat exposes explicit, bounded cloud tools for memory recall, remember,
forget, aircraft preferences, and semantic flight history. They execute
backend-internally and cannot reach DCS, the client filesystem, or shell. All
records are scoped by the authenticated user. Missing values stay missing.

The backend attaches the aircraft name from the first valid catalog epoch to the
current flight session. A flight record contains timestamps and own-aircraft
identifier only — no raw telemetry, cockpit snapshot, audio, event totals, or
inferred habit.

## Milestone 7 deterministic-habit contract

The backend `FlightStatsManager` observes the same deterministic rule
transitions used by live monitoring. At aircraft change or session end it
creates a versioned semantic summary scoped to the authenticated user. The
summary contains a UUID, own-aircraft name, and an allowlisted map of rule IDs
to activation counts — no raw values, no snapshots, no timeseries.

A rule is included with a zero only if its required telemetry was usable during
that flight. Rules that were never evaluable are omitted, preserving unknown
coverage rather than guessing an all-clear. Cloud insertion is idempotent by
user and summary UUID. `get_pilot_habits` calculates coverage-aware counts and
returns a deterministic server-generated sentence; the LLM is required to repeat
that sentence and forbidden from deriving counts from memory or generic flight
history.
