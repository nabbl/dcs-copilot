# Client/cloud protocol version 1

The same protocol is used against localhost and the production service. The
initial transport is one persistent WebSocket at `/v1/realtime`. Production
connections require TLS (`wss://`); plaintext `ws://` is rejected by the client
unless the host is loopback.

## Control envelope

Control messages are compact JSON text frames:

```json
{
  "protocol_version": 1,
  "type": "ptt.start",
  "message_id": "uuid",
  "correlation_id": "optional-request-uuid",
  "payload": {}
}
```

Every response to a request uses the request's `message_id` as its
`correlation_id`. Version mismatches are fatal. A syntactically valid unknown
message type produces an `unsupported_message` error without crashing or
closing an otherwise valid session.

The v1 registry includes `hello`, `authenticate`, `session.start`,
`session.end`, `ptt.start`, `ptt.end`, `assistant.text`, `assistant.interrupt`,
`tool.request`, `tool.result`, aircraft/event lifecycle messages,
`connection.status`, and `error`. Aircraft tool and semantic event behavior is
implemented; unrelated future lifecycle types remain forward-compatible.

## Session sequence

```text
cloud  -> hello
client -> authenticate
cloud  -> connection.status (authenticated)
client -> session.start (session ID + audio format)
cloud  -> connection.status (session active)

client -> assistant.interrupt
client -> ptt.start
client -> binary AUDIO_INPUT packets while held
client -> ptt.end
cloud  -> event (utterance.received)

client -> session.end
```

The development authenticator compares `DCS_COPILOT_ACCESS_TOKEN` with the
server's `DCS_COPILOT_DEV_TOKEN`. This proves the protocol flow only; it is not
the device-login, refresh-token, revocation, or rate-limiting system required
for production. Both peers enforce a bounded handshake timeout so an idle or
malicious half-open connection cannot occupy a session indefinitely.

## Binary media envelope

Audio is not base64 encoded. Each WebSocket binary frame begins with the
network-byte-order header `!4sBBIQ`:

| Field | Size | Value |
| --- | ---: | --- |
| Magic | 4 bytes | `DCSC` |
| Protocol version | 1 byte | `1` |
| Media kind | 1 byte | `1` input, `2` output |
| Sequence | 4 bytes | unsigned, wraps at 2³² |
| Timestamp | 8 bytes | monotonic milliseconds |
| Payload | remaining bytes | PCM for v1 |

The negotiated v1 audio formats are mono `pcm_s16le`: 16 kHz input and 24 kHz
output, in 20 ms chunks by default. Media packets are represented independently
of the WebSocket adapter, allowing a future WebRTC implementation to retain the
control/session layer.

The cloud accepts `AUDIO_INPUT` only during an active PTT turn. The client
accepts only `AUDIO_OUTPUT` from the cloud. PTT release, not silence detection,
is authoritative. The uplink queue is bounded; excess audio may be dropped, but
reserved control capacity preserves FIFO delivery of `ptt.end` after all
accepted audio.

## Voice and aircraft-tool sequence

The cloud returns a diagnostic event after each bounded turn:

```json
{
  "event_type": "utterance.received",
  "session_id": "uuid",
  "audio_bytes": 6400,
  "audio_chunks": 10,
  "duration_ms": 200
}
```

The receipt is followed by cloud voice processing. A cockpit-dependent question
may insert one or more local tool calls before response text/audio:

```text
client -> ptt.end
cloud  -> event (utterance.received)
cloud  -> tool.request
client -> tool.result (correlated)
cloud  -> binary AUDIO_OUTPUT chunks
cloud  -> assistant.text
```

Tool requests use their control `message_id` as the request ID. Tool results
must place that ID in `correlation_id`:

```json
{
  "protocol_version": 1,
  "type": "tool.request",
  "message_id": "request-uuid",
  "payload": {
    "tool_version": 1,
    "tool": "get_aircraft_state",
    "arguments": {"fields": ["refueling_probe", "master_caution"]}
  }
}
```

```json
{
  "protocol_version": 1,
  "type": "tool.result",
  "message_id": "result-uuid",
  "correlation_id": "request-uuid",
  "payload": {
    "tool_version": 1,
    "tool": "get_aircraft_state",
    "ok": true,
    "result": {
      "fields": {
        "refueling_probe": {
          "status": "AVAILABLE",
          "value": true,
          "updated_at": 123.4,
          "source": "DCS-BIOS:EXT_REFUEL_PROBE"
        }
      }
    }
  }
}
```

The allowlist is `get_aircraft_state`, `get_active_issues`,
`get_recent_events`, and `get_flight_phase`. State requests require explicit
safe normalized fields and never accept `raw` or a complete snapshot. Recent
deterministic rule events are capped at 20 records and a 300-second window.
Unknown tools,
arguments, versions, unsolicited results, and correlation mismatches fail
closed. The cloud times out pending calls and fails them immediately on client
disconnect.

`get_active_issues` also reports `coverage` and the IDs of rules that could not
be evaluated with current telemetry. An empty issue list therefore never turns
missing telemetry into an unsupported “all clear.”

## Proactive semantic events

Milestone 5 uses versioned, bounded `event.raised` and `event.resolved` control
messages. A raised event contains only deterministic rule output:

```json
{
  "protocol_version": 1,
  "type": "event.raised",
  "message_id": "message-uuid",
  "payload": {
    "event_version": 1,
    "event_id": "event-uuid",
    "rule_id": "FA18_REFUELING_PROBE_LEFT_OUT",
    "status": "RAISED",
    "severity": "ADVISORY",
    "aircraft": "FA-18C_hornet",
    "flight_phase": "CRUISE",
    "message": "Refueling probe is still out.",
    "data": {"flight_phase": "CRUISE"}
  }
}
```

The matching `event.resolved` reuses `event_id` and has status `RESOLVED` or
`DISABLED`. Unknown versions, extra fields, invalid severities, and control-type
or status mismatches are rejected. No raw addresses, full normalized snapshot,
enemy/world state, or arbitrary client data is accepted.

An accepted raised event may produce binary `AUDIO_OUTPUT` followed by an
`assistant.text` carrying `proactive: true` and the event ID. Advisories are
dropped while another response or PTT turn is active; warnings and critical
events may replace an active cloud response. `ptt.start`,
`assistant.interrupt`, or the matching resolution cancels active proactive
speech. The client does not replay events accumulated during a disconnect.
