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

The governing rule is: **the gaming PC runs DCS; the cloud runs AI**.

The client is a small read-only telemetry and audio peripheral. It owns DCS-BIOS
ingestion, aircraft normalization, phase detection, deterministic rules,
semantic event history, local speech policy, PTT, audio capture/playback, and
the authenticated cloud connection. It does not contain an OpenAI credential or
run neural STT, TTS, turn detection, embeddings, vector search, or an LLM.

The cloud owns Pipecat, STT, conversational orchestration, provider-isolated
LLM and TTS services, account data, memory, usage metering, and subscriptions.
It learns live aircraft facts only by issuing narrow, versioned tool requests to
the connected client. Raw DCS-BIOS telemetry is never continuously uploaded.

`shared` contains transport-neutral protocol schemas. It must not contain
business logic or force the client to install cloud dependencies. The initial
transport will be an authenticated WebSocket; media and control abstractions
must allow a later move to WebRTC without redesigning the Copilot Brain.

## Runtime boundaries

```text
CUSTOMER GAMING PC                         DCS COPILOT CLOUD

DCS -> DCS-BIOS -> thin client            authenticated session gateway
                  |- normalized state       -> Pipecat
                  |- phase + rules             |- STT provider
                  |- semantic events ---------->|- cloud proactive TTS
                  |- PTT audio ---------------->|- LLM provider
                  |- response playback <-------|- TTS provider
                  `- speech policy             `- memory + metering
```

Client-to-cloud data is limited by default to intentional PTT audio, requested
semantic fields, narrow tool results, semantic events, and explicitly allowed
session statistics. Unavailable cockpit values remain unavailable and are never
guessed locally or in the cloud.

## Existing-code disposition

The existing repository was inspected before this decision.

Retain in the client:

- the incremental DCS-BIOS protocol parser and passive multicast client;
- generated-control registry loading and `_ACFT_NAME` aircraft detection;
- normalized `TelemetryValue` models and F/A-18C/generic adapters;
- compact state history and hysteretic flight-phase detection;
- the deterministic rule engine and verified Hornet rules;
- normalized JSONL replay and its tests;
- passive diagnostics and structured logging.

Remove from the client:

- Pipecat and its local audio pipeline;
- Kokoro and downloaded voice models;
- Silero VAD and Smart Turn;
- Jarvis and OpenAI STT clients;
- the OpenAI Responses client and customer-side API-key configuration;
- local conversational prompts and LLM tool registration.

The copied Jarvis WebSocket STT adapter is not retained. It is unnecessary when
STT runs in the cloud and would preserve the wrong dependency direction. Hermes
Agent is not part of the new cloud brain.

DCS-BIOS remains an external installation. The product consumes its published
multicast protocol and generated control metadata; it does not copy, modify, or
silently redistribute DCS-BIOS.

## Client resource contract

The production client has no AI optional extra and no dependency on Pipecat,
OpenAI, CUDA, Torch, ONNX, local model files, or vector databases. With no PTT
activity it performs only socket-driven DCS ingestion and inexpensive local
state/rule evaluation. Microphone capture is off while PTT is released.

Milestone 1 records process CPU time, resident memory, frame/update throughput,
and parser errors through a repeatable benchmark. The definitive performance
acceptance test must additionally measure DCS frametime on Windows in a
demanding rendered mission; a development-machine microbenchmark cannot prove
that requirement by itself.

## Safety and multiplayer boundary

The client is initially read-only. It does not send DCS-BIOS or DCS commands,
modify aircraft files, or inspect world objects, targets, enemy units, or hidden
mission state. In particular, it does not use `LoGetWorldObjects`,
`LoGetObjectById`, `LoGetTargetInformation`, or
`LoGetLockedTargetInformation`.

CommonData and other server-restricted values require explicit validity proof.
If multiplayer restrictions remove a value, adapters and rules disable the
dependent capability. Compatibility and Integrity Check claims require the
live test matrix in `docs/multiplayer-validation.md`.

## Dependency and deployment policy

Each component has its own manifest and virtual environment boundary:

- `client/pyproject.toml`: the shared schema package plus narrowly justified
  WebSocket, PortAudio, and Windows hotkey dependencies; no cloud or AI stack;
- `cloud/pyproject.toml`: FastAPI/Uvicorn session gateway dependencies, never
  installed on customer machines;
- `shared/pyproject.toml`: standard-library-only protocol schemas.

The top-level project is orchestration and documentation only. Python remains
acceptable for the prototype client because the retained runtime is I/O-bound
and model-free. The versioned protocol must remain implementable by a future
Rust client.

## Reset milestone sequence

1. **Thin DCS client (implemented):** retained telemetry, normalization, Hornet rules, replay,
   diagnostics, tests, and client performance instrumentation. No AI.
2. **Client/cloud protocol (implemented):** localhost server, authentication placeholder,
   persistent session, PTT capture, audio transport, and basic request/response.
3. **Cloud Pipecat voice (implemented):** cloud OpenAI STT/LLM/TTS and streamed
   response audio.
4. **Aircraft tools (implemented):** versioned local requests for selected
   state, active deterministic issues, recent rule events, and flight phase.
5. **Proactive warnings (implemented, cloud-connected):** bounded semantic
   events, local speech policy, and interruptible cloud TTS advisories.
6. **Accounts and memory:** production authentication, PostgreSQL, memories,
   preferences, and flight sessions.
7. **Habit learning:** deterministic end-of-flight statistics and stored habit
   calculations.
8. **Commercial foundation:** metering, entitlements, devices, rate limiting,
   and operations monitoring.

Milestones 3 through 5 preserve the original dependency boundary: Pipecat and
every AI provider exist only in the cloud package, while telemetry and tool
execution remain in the thin client.

## Milestone 1 implementation contract

Milestone 1 exposes only:

- `dcs-copilot status` for bounded DCS-BIOS and resource diagnostics;
- `dcs-copilot watch` for normalized or explicitly selected raw controls;
- `dcs-copilot replay <recording>` for deterministic offline development;
- `dcs-copilot benchmark` for a repeatable synthetic client workload.

The status output must explicitly report `AI inference running locally: NO`.
The Milestone 1 benchmark remains available after later client milestones.

## Milestone 2 implementation contract

Protocol version 1 separates JSON control messages from binary media packets.
Every control envelope carries `protocol_version`, `message_id`, optional
`correlation_id`, a type, and a payload. Binary packets carry a stable magic,
version, media kind, sequence number, monotonic timestamp, and payload. The
envelope is independent of WebSocket so WebRTC can replace the transport later.

The FastAPI gateway sends `hello`, authenticates a development access token,
starts one session, accepts PCM only between `ptt.start` and `ptt.end`, and
returns an `utterance.received` receipt. Unknown controls return a non-fatal
error. PTT release is authoritative; neither side runs VAD or turn inference.

The client opens PortAudio capture only after PTT press and closes it before
sending `ptt.end`. PCM enters a bounded queue with reserved control capacity so
audio congestion cannot prevent the end-of-turn signal. PTT press first stops
assistant playback and sends `assistant.interrupt`. Cloud failures reconnect
with bounded backoff while the independent DCS task continues running.

Plain `ws://` connections are accepted only for loopback development. Any
non-loopback service URL must use `wss://`. The placeholder token is not
production authentication and must be replaced by device login and short-lived
credentials in the account milestone.

## Milestone 3 voice contract

Each authenticated session owns one persistent Pipecat conversation pipeline.
PTT release injects the externally bounded 16 kHz PCM turn into cloud STT; the
provider-neutral LLM produces a concise response and cloud TTS streams 24 kHz
PCM back without waiting for the full utterance. `STTProvider`, `LLMProvider`,
and `TTSProvider` isolate the initial OpenAI implementations. Pressing PTT while
the assistant speaks stops local playback, sends `assistant.interrupt`, cancels
the active gateway task, and injects a Pipecat interruption frame.

## Milestone 4 aircraft-tool contract

The LLM can advertise only `get_aircraft_state`, `get_active_issues`,
`get_recent_events`, and `get_flight_phase`. Tool schema version 1 validates
names, arguments, field counts, history windows, and result shape at both trust
boundaries. `get_aircraft_state` requires an explicit field list and rejects
raw state, warning-light maps, and every unrecognized field. Results preserve
`AVAILABLE`, `STALE`, and `UNAVAILABLE` status; an unavailable value is returned
as `null`, never inferred.

The gateway correlates each `tool.result` with the request message ID and rejects
unsolicited or mismatched responses. Pending calls have a short timeout and fail
when the WebSocket disconnects. A failed call becomes structured unavailable
tool data so the LLM can give a concise honest answer. No shell, filesystem,
Lua, control-writing, enemy/world-state, or arbitrary DCS capability crosses
this interface. Milestone 4 does not add proactive delivery, local warning
audio, account memory, or any Milestone 5 behavior.

## Milestone 5 proactive-speech contract

The local `EventManager` converts rule activations, resolutions, and telemetry
disablement into versioned semantic events with stable event IDs. It retains a
bounded history and never serializes raw DCS-BIOS or a cockpit snapshot. Replay
drives the same event manager as live telemetry.

`SpeechPolicy` remains authoritative on the client. `MINIMAL` permits only
critical activations, `NORMAL` permits warnings plus explicitly relevant
advisories, and `COACH` permits all cooldown-eligible severities. Resolutions
are published only for events whose activation policy allowed. PTT suppresses a
new local announcement and remains the authoritative barge-in signal.

The gateway validates `event.raised` and `event.resolved`. It streams the
deterministic short rule message through provider-neutral cloud TTS rather than
asking an LLM to invent safety phrasing. Warnings can replace an active cloud
response; advisories do not. PTT and a correlated resolution cancel an active
announcement.

Per the revised product requirement, Milestone 5 does not ship prerecorded
audio or promise warning speech without a cloud connection. DCS monitoring,
rules, normalized state, and bounded event history continue locally during a
disconnect, but speech resumes only for new eligible events after reconnection.
No Milestone 6 account, memory, or persistence work is included.
