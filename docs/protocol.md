# Client/cloud protocol version 2

Protocol version 2 is a **breaking change**. Protocol version 1 is no longer
supported. The client and cloud must be upgraded together; a version-1 client
cannot connect to a version-2 gateway and vice versa.

The same protocol is used against localhost and the production service. The
realtime WebSocket endpoint is `/v2/realtime`. HTTP account operations remain at
`/v1/auth`. Production connections require TLS (`wss://`); plaintext `ws://` is
rejected by the client unless the host is loopback.

## Architecture overview

In protocol version 2 the client is a generic read-only DCS and audio transport.
It continuously sends a decoded own-cockpit control catalog, an
initial value snapshot, and changed-value deltas — independent of PTT. The
backend receives the raw decoded telemetry stream, holds it bounded in
authenticated session memory, and owns all normalization, phase detection,
deterministic rules, checklists, semantic events, speech policy, habit
statistics, and MARA tool execution. Raw telemetry is never persisted or logged
as full snapshots or time series; semantic account, history, and habit records
may persist as documented in `docs/accounts.md`.

Only own-aircraft modules and CommonData passive DCS-BIOS outputs are accepted
on the cockpit stream. `coach.telemetry` separately carries bounded normalized
ownship and selected-reference observations. References are legal only when the
same message reports DCS world-object export as allowed. No complete world dump,
filesystem data, targets, or hidden mission state crosses the interface.

## Control envelope

Control messages are compact JSON text frames:

```json
{
  "protocol_version": 2,
  "type": "ptt.start",
  "message_id": "uuid",
  "correlation_id": "optional-request-uuid",
  "payload": {}
}
```

Every response to a request uses the request's `message_id` as its
`correlation_id`. Version mismatches are fatal. A syntactically valid unknown
message type produces an `unsupported_message` error without closing an
otherwise valid session.

## Coach telemetry

`coach.telemetry` schema version 1 contains a sequence, observation timestamp,
the four explicit DCS capability flags, optional normalized ownship data, and at
most two references: one `LEAD_AIRCRAFT` and one `CARRIER`. The shared validator
rejects references whenever `world_object_export` is false and rejects ownship
data whenever `ownship_export` is false. Client and cloud fail closed when the
loopback DCS export becomes stale.

The language model never receives this message. A backend Coach coordinator
converts it into deterministic relative observations, semantic feedback, and
bounded debrief facts exposed through high-level Coach tools.

The v2 message type registry: `hello`, `authenticate`, `session.start`,
`session.end`, `ptt.start`, `ptt.end`, `pilot.text`, `assistant.text`,
`audio.input`, `audio.output`, `assistant.interrupt`, `connection.status`,
`error`, `event`, `telemetry.catalog`, `telemetry.snapshot`, `telemetry.delta`.
The registry also includes the separately validated `coach.telemetry` stream.

## Session sequence

```text
cloud  -> hello
client -> authenticate
cloud  -> connection.status (authenticated)
client -> session.start (session ID + audio format)
cloud  -> connection.status (session active)

// Telemetry stream — continuous, independent of PTT:
client -> telemetry.catalog  (chunked; fresh epoch per aircraft slot or reconnect)
client -> telemetry.snapshot (chunked initial values, same epoch)
cloud  -> assistant.text     (cockpit welcome, proactive: true)
client -> telemetry.delta    (changed values at 10–20 Hz)

// PTT voice turn:
client -> assistant.interrupt
client -> ptt.start
client -> binary AUDIO_INPUT packets while held
client -> ptt.end
cloud  -> event (utterance.received)
cloud  -> binary AUDIO_OUTPUT chunks
cloud  -> pilot.text
cloud  -> assistant.text

client -> session.end
```

Authentication uses a short-lived signed access token from the cloud HTTP
account API. The token is bound to `device_id`; an expired, tampered, or
wrong-device token closes authentication. Refresh rotation occurs over HTTPS
outside this protocol. `DCS_COPILOT_DEV_TOKEN` remains a loopback-development
escape hatch with no account identity or memory access. Both peers enforce a
bounded handshake timeout.

## Telemetry stream

The client sends a contiguous sequence of catalog → snapshot → deltas for each
aircraft session. A new UUID epoch signals a fresh aircraft slot or reconnect;
the backend resets its session-memory state and closes the active MARA pipeline.

### Control identity

Every catalog entry and decoded value carries a stable `identity` object that
identifies the cockpit control by symbolic name, not by numeric DCS-BIOS
address or memory offset:

```json
{
  "module": "FA-18C_hornet",
  "identifier": "MASTER_CAUTION_LT",
  "output_type": "integer",
  "output_index": 0
}
```

`output_type` is `"integer"` or `"string"`. `output_index` distinguishes
multiple outputs of the same type on the same control. The tuple
`(module, identifier, output_type, output_index)` is the stable, unique key.

### Catalog message

Sent once per epoch, possibly chunked. Each entry describes one control output:

```json
{
  "protocol_version": 2,
  "type": "telemetry.catalog",
  "message_id": "uuid",
  "payload": {
    "telemetry_version": 1,
    "epoch": "epoch-uuid",
    "sequence": 0,
    "aircraft": "FA-18C_hornet",
    "chunk_index": 0,
    "chunk_count": 1,
    "entries": [
      {
        "identity": {"module": "FA-18C_hornet", "identifier": "MASTER_CAUTION_LT",
                     "output_type": "integer", "output_index": 0},
        "description": "Master Caution light",
        "integer_max": 1
      }
    ]
  }
}
```

Entries never include DCS-BIOS addresses, masks, shifts, or filesystem paths.
The catalog may contain up to 256 entries per chunk and up to 64 chunks per
epoch. The backend caps session state at 4 096 registered controls per
connection.

### Snapshot message

Follows the complete catalog for the same epoch. Contains the current value of
every catalogued control:

```json
{
  "protocol_version": 2,
  "type": "telemetry.snapshot",
  "message_id": "uuid",
  "payload": {
    "telemetry_version": 1,
    "epoch": "epoch-uuid",
    "sequence": 1,
    "aircraft": "FA-18C_hornet",
    "chunk_index": 0,
    "chunk_count": 1,
    "values": [
      {
        "identity": {"module": "FA-18C_hornet", "identifier": "MASTER_CAUTION_LT",
                     "output_type": "integer", "output_index": 0},
        "available": true,
        "value": 0,
        "observed_at_ms": 1234567
      }
    ]
  }
}
```

An unavailable value sets `available: false` and `value: null`. The backend
triggers a cockpit welcome announcement after the complete snapshot is received.

### Delta message

Sent continuously after the snapshot, carrying only controls whose decoded
value changed since the previous message. Sequences are monotonically
increasing within an epoch:

```json
{
  "protocol_version": 2,
  "type": "telemetry.delta",
  "message_id": "uuid",
  "payload": {
    "telemetry_version": 1,
    "epoch": "epoch-uuid",
    "sequence": 42,
    "aircraft": "FA-18C_hornet",
    "chunk_index": 0,
    "chunk_count": 1,
    "values": [
      {
        "identity": {"module": "FA-18C_hornet", "identifier": "MASTER_CAUTION_LT",
                     "output_type": "integer", "output_index": 0},
        "available": true,
        "value": 1,
        "observed_at_ms": 1234999
      }
    ]
  }
}
```

A delta must contain at least one value. A message for an unrecognized epoch is
rejected. The backend never persists raw telemetry values; all state is bounded
in the authenticated session's in-process memory.

## Binary media envelope

Audio is not base64 encoded. Each WebSocket binary frame begins with the
network-byte-order header `!4sBBIQ`:

| Field | Size | Value |
| --- | ---: | --- |
| Magic | 4 bytes | `DCSC` |
| Protocol version | 1 byte | `2` |
| Media kind | 1 byte | `1` input, `2` output |
| Sequence | 4 bytes | unsigned, wraps at 2³² |
| Timestamp | 8 bytes | monotonic milliseconds |
| Payload | remaining bytes | PCM |

The negotiated v2 audio formats are mono `pcm_s16le`: 16 kHz input and 24 kHz
output, in 20 ms chunks by default. Media packets are transport-neutral,
allowing a future WebRTC implementation to retain the control/session layer.

The backend accepts `AUDIO_INPUT` only during an active PTT turn. The client
accepts only `AUDIO_OUTPUT` from the backend. PTT release, not silence
detection, is authoritative. The uplink queue is bounded; excess audio may be
dropped, but reserved control capacity preserves FIFO delivery of `ptt.end`
after all accepted audio.

## Voice turn sequence

The backend returns a diagnostic event after each bounded PTT turn:

```json
{
  "event_type": "utterance.received",
  "session_id": "uuid",
  "audio_bytes": 6400,
  "audio_chunks": 10,
  "duration_ms": 200
}
```

The receipt is followed by cloud voice processing. The LLM reads aircraft
state, active issues, recent events, flight phase, and checklist gaps directly
from the backend's session-memory telemetry store. No `tool.request` message is
sent to the client; all aircraft tool execution is backend-internal.

```text
client -> ptt.end
cloud  -> event (utterance.received)
cloud  -> binary AUDIO_OUTPUT chunks
cloud  -> pilot.text
cloud  -> assistant.text
```

`pilot.text` contains the STT transcript. `assistant.text` contains the
response text. The desktop Activity view shows only `pilot.text` and
`assistant.text`; it never shows raw telemetry, tokens, or controller state.
Assistant muting is a local playback control and does not affect protocol
traffic.

## Proactive speech

The backend's deterministic rule engine observes the telemetry stream and
generates `RAISED`, `RESOLVED`, and `DISABLED` events internally. When speech
policy permits, the backend synthesises the deterministic rule message through
the configured cloud TTS provider and streams `AUDIO_OUTPUT`. After delivery it
sends:

```json
{
  "protocol_version": 2,
  "type": "assistant.text",
  "message_id": "uuid",
  "payload": {
    "text": "Refueling probe is still out.",
    "proactive": true,
    "event_id": "event-uuid"
  }
}
```

Advisories are dropped while a PTT turn or voice response is active; warnings
and critical events may replace an active response. `ptt.start` or
`assistant.interrupt` cancels active proactive speech. No `event.raised` or
`event.resolved` control message is sent to the client; event management is
entirely backend-side.

## Flight-session epoch

A new epoch in `telemetry.catalog` signals an aircraft slot change or a fresh
connection. The backend interrupts and closes the active MARA pipeline, resets
its session-memory raw telemetry state, and starts the cockpit welcome flow for
the new slot. Explicit account memories and preferences are not erased.

The backend attaches the aircraft name from the first valid catalog's `aircraft`
field to the authenticated user's flight session record. The flight session
closes on `session.end` or disconnect.

Cloud memory, preference, and habit tools are internal Pipecat functions. They
never produce client-facing messages and cannot reach DCS or the client's
filesystem.

## Migration from protocol v1

Protocol v1 clients and servers are incompatible with protocol v2 and cannot
negotiate a shared version. Both sides must be upgraded at the same time. No
fallback or negotiation path is provided.
