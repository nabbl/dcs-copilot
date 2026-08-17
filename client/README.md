# DCS Copilot thin client

The in-cockpit assistant is **MARA — Mission-Aware Realtime Assistant**.

The client is a generic read-only DCS-BIOS and audio transport. It ingests the
DCS-BIOS multicast stream, decodes own-aircraft control outputs, and
continuously publishes a decoded control catalog, an initial value snapshot, and
changed-value deltas to the cloud — independent of PTT. It captures PCM only
while PTT is held and connects to the DCS Copilot service through the shared
versioned protocol (v2, `/v2/realtime`, auth at `/v1/auth`). It contains no AI
model, no OpenAI credential, and performs no aircraft normalization, rule
evaluation, phase detection, checklist execution, event management, or speech
policy. All semantic processing is authoritative on the backend.

The Windows build includes a Qt desktop shell for login, DCS Saved Games
selection, DCS-BIOS installation/repair, settings, status, and runtime control.
The desktop can learn separate HOTAS buttons for PTT and assistant mute. The
Activity tab filters raw runtime output and shows only recognized pilot speech
and the resulting MARA response. Short generated local tones confirm mute and
unmute without requiring cloud TTS.

## Telemetry publishing

The telemetry publisher builds a stable control catalog from the DCS-BIOS
control registry and detected aircraft module. Each catalog entry identifies a
control output by its symbolic name (`module`, `identifier`, `output_type`,
`output_index`) — not by numeric DCS-BIOS address. On each new aircraft slot
or reconnect the publisher generates a fresh epoch UUID, sends the complete
catalog in chunks, sends a complete value snapshot, then sends coalesced
changed-value deltas at 10–20 Hz. Only own-aircraft modules and CommonData
passive DCS-BIOS outputs are published on this stream. A separate packaged
spatial provider sends normalized ownship and at most one selected lead/carrier
only when DCS permits world-object export. No complete world dump, filesystem,
target, or hidden mission data is forwarded and no DCS writes are ever issued.

## PTT and audio

Microphone capture opens only after PTT is pressed and closes before `ptt.end`
is sent. There is no open-microphone mode, VAD, or background capture. PTT
press first stops assistant playback and sends `assistant.interrupt`. Cloud
failures reconnect with bounded backoff while the independent DCS ingestion
task continues running.

## Authentication

The desktop signs in through the backend HTTP auth API at `/v1/auth` and stores
only its rotating refresh credential in Windows Credential Manager. Access
tokens remain in memory and are refreshed before each WebSocket reconnect. The
client sends the short-lived token and a stable, random device identifier during
the handshake.

The Windows installer can configure every detected DCS Saved Games tree. It
downloads a pinned DCS-Skunkworks DCS-BIOS release, verifies its SHA-256
digest, backs up an existing DCS-BIOS folder and `Export.lua`, installs the
read-only `MARASpatial.lua`, and adds both `dofile` entries exactly once. The same operation is available from
the UI and as `mara setup-dcs [path]`.

## CLI commands

```text
mara status [--wait N]          bounded DCS-BIOS and cloud diagnostics
mara run [--stdin-ptt] [--coach-recording FILE]
                                DCS monitoring, cloud session, and opt-in replay data
mara watch [--module M]         decoded DCS-BIOS output changes
mara setup-dcs [path]           install DCS-BIOS and configure Export.lua
mara coach replay FILE --exercise EXERCISE
                                replay normalized Coach data (developer workspace)
```

The legacy `dcs-copilot` command remains available as an alias.

`status` also reports ownship, cockpit, world-export, and derived Coach
availability. It reports `AI inference running locally: NO`. `--stdin-ptt` replaces the
Windows hotkey with Enter for POSIX development.
