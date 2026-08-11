# DCS Copilot thin client

The in-cockpit assistant is **MARA — Mission-Aware Realtime Assistant**.

The customer-side read-only DCS telemetry and audio peripheral. The Windows
build includes a Qt desktop shell for login, DCS Saved Games selection,
DCS-BIOS installation/repair, settings, status, and runtime control. It retains
aircraft normalization and deterministic safety logic locally, captures PCM
only while PTT is held, and connects to the DCS Copilot service through the
shared versioned protocol. It contains no AI model or provider credential.
The desktop can learn separate HOTAS buttons for PTT and assistant mute. The
Activity tab filters raw runtime output and shows only recognized pilot speech
and the resulting MARA response. Short generated local tones confirm mute
and unmute without requiring cloud TTS.
It also executes the four Milestone 4 aircraft tools locally against normalized
state, deterministic rules, bounded history, and flight phase. Tool calls are
read-only, allowlisted, and never expose raw or arbitrary DCS access.
Deterministic rule transitions also feed a bounded local `EventManager`.
`COPILOT_SPEECH_MODE` selects `MINIMAL`, `NORMAL`, or `COACH`; the policy sends
only eligible semantic events to cloud TTS and never uploads a cockpit snapshot.
There is intentionally no local warning-audio pack in this build.

Milestone 6 keeps account data off the gaming PC. The desktop signs in through
the backend HTTP API and stores only its rotating refresh credential in Windows
Credential Manager. Access tokens remain in memory and are refreshed before
WebSocket reconnects. The client sends the short-lived token and a stable,
random device identifier during the handshake. It reports only a versioned
aircraft identifier for the cloud flight-session record; no cockpit snapshot or
telemetry accompanies that metadata. Password verification, token hashes,
memory, and database logic remain cloud-side.

The Windows installer can configure every detected DCS Saved Games tree. It
downloads a pinned DCS-Skunkworks DCS-BIOS release, verifies its SHA-256 digest,
backs up an existing DCS-BIOS folder and `Export.lua`, and adds the standard
DCS-BIOS `dofile` exactly once. The same operation is available from the UI and
as `dcs-copilot setup-dcs [path]`.

Milestone 7 adds local `FlightStatsManager` aggregation over the same
deterministic rules. On flight end it sends only an allowlisted rule/count map
with explicit telemetry coverage. Unavailable rules are omitted, never guessed
clear. Summaries remain bounded and pending until a correlated cloud ack; no
raw or complete normalized state is uploaded.

The F/A-18C rule engine supports declarative deterministic `RuleDefinition`
entries for configuration, phase, transition, and command-vs-actual mismatch
checks. The first carrier-launch, post-launch, combat-mode, probe, and recovery
rules use normalized semantic fields such as `carrier_launch_sequence`,
`takeoff_trim_confirmed`, `wing_fold_spread`, and `carrier_recovery`; missing
DCS-BIOS controls disable affected rules instead of guessing. Actual stabilator
trim magnitude remains unsupported unless an IC-safe read-only export is added.
Each rule also declares catalogue metadata: category, minimum chatter mode,
severity, feasibility, false-positive risk, required fields, timing, description,
and source reference. `SpeechPolicy` uses the deterministic rule's
`minimum_mode` so `MINIMAL`, `NORMAL`, and `COACH` remain cumulative without
letting the cloud model decide whether a cockpit condition exists.

Useful diagnostics:

```text
dcs-copilot rules
dcs-copilot rules --active
dcs-copilot rule explain HOOK_DOWN_OUTSIDE_RECOVERY
dcs-copilot check carrier-launch
dcs-copilot checklist status before-taxi
dcs-copilot checklist explain seat-armed --stage before-taxi
```

The checklist engine is also deterministic and local-only. It evaluates
data-driven checklist items against normalized aircraft state, recent state
history transitions, derived rule conditions, and explicitly confirmed manual
items. Checklist tool calls expose only checklist IDs, item labels, local status,
and reasons; they do not upload raw cockpit state.
