# F/A-18C situational-awareness capability discovery

Status: phase-one tooling implemented; live DCS evidence not yet collected.

This report deliberately distinguishes `UNKNOWN` from `UNSUPPORTED`. No radar,
RWR, or SA capability will be implemented from a guessed field name. Results
must come from a controlled recording made against a named DCS and DCS-BIOS
version.

## Safety boundary

The probe calls only DCS `list_indication(indicator_id)`. It does not enumerate
world objects, call target-information APIs, capture screenshots, use OCR or an
LLM, or upload indication contents. The Lua socket and Python reader both bind
to `127.0.0.1`. DCS is never commanded or mutated.

Raw recordings are local development artifacts ignored by Git. Normal MARA
operation neither starts the probe nor retains recordings.

## Current capability matrix

| Capability | Candidate source | Status | Reliability | Evidence / next check |
|---|---|---:|---:|---|
| Master Arm state | DCS-BIOS `MASTER_ARM_SW` | SUPPORTED | HIGH | Existing normalized Hornet adapter and tests |
| A/A or A/G combat mode selected | DCS-BIOS master-mode lights | SUPPORTED | HIGH | Existing normalized Hornet adapter and tests |
| Countermeasure system state | DCS-BIOS | UNKNOWN | UNKNOWN | Inspect installed control metadata and exercise each switch |
| Radar powered / switch position | DCS-BIOS | UNKNOWN | UNKNOWN | Locate candidate controls and record OFF/STBY/OPR |
| Radar operating mode | indication / DCS-BIOS | UNKNOWN | UNKNOWN | Record RWS and TWS transitions |
| Radar range | indication / DCS-BIOS | UNKNOWN | UNKNOWN | Change range with the radar page displayed |
| Radar contact count | indication | UNKNOWN | UNKNOWN | Compare empty, one-contact, and multi-contact recordings |
| Radar track metadata | indication | UNKNOWN | UNKNOWN | Inspect raw text; do not assume graphical symbols export |
| Designated radar track | indication | UNKNOWN | UNKNOWN | Record designation and undesignation transitions |
| Radar STT / lock | indication | UNKNOWN | UNKNOWN | Record acquisition and loss separately from designation |
| Shoot cue | cockpit indication | UNKNOWN | UNKNOWN | Record cue appearance and disappearance |
| RWR powered | DCS-BIOS / indication | UNKNOWN | UNKNOWN | Record power switch and display state |
| RWR failure | DCS-BIOS / cockpit light | UNKNOWN | UNKNOWN | Verify a specific failure indication, not a generic control |
| RWR emitter identity | indication | UNKNOWN | UNKNOWN | Record search emitters of known type |
| RWR emitter bearing | indication | UNKNOWN | UNKNOWN | Determine whether symbol coordinates are exported |
| Incoming radar track/lock | indication | UNKNOWN | UNKNOWN | Separate search, track, and lock experiments |
| Missile launch warning | indication / cockpit light | UNKNOWN | UNKNOWN | Require an unambiguous launch-specific transition |
| SA tracks | indication | UNKNOWN | UNKNOWN | Compare empty and populated SA pages |
| SA affiliation / HAFU | indication | UNKNOWN | UNKNOWN | Verify text or metadata; do not infer from absent graphics |
| SA altitude / Mach | indication | UNKNOWN | UNKNOWN | Inspect a controlled known track |
| SA selected track | indication | UNKNOWN | UNKNOWN | Change selection while all other state remains stable |

`SUPPORTED` means a versioned recording and deterministic mapping exist.
`PARTIAL` means only some fields or display conditions are observable.
`UNSUPPORTED` requires positive evidence that the tested sources do not expose
the value. `UNKNOWN` means the experiment has not established an answer.

## Pinned DCS-BIOS metadata findings

The official DCS-BIOS v0.11.5 Hornet module and generated control reference
confirm that the following structured outputs exist. This is metadata evidence,
not yet a live reliability result, so the relevant capability rows remain
`UNKNOWN` until a recording verifies that each output is present and behaves as
documented in the current DCS build.

| Control | Candidate interpretation | Declared values |
|---|---|---|
| `RADAR_SW` | Physical radar switch position | `0 OFF`, `1 STBY`, `2 OPR`, `3 EMERG` |
| `RWR_LOWER_LT` | RWR green power light | `0 off`, `1 on` |
| `RWR_FAIL_LT` | RWR red failure light | `0 off`, `1 on` |
| `RWR_AUDIO_CTRL` | RWR audio knob fraction | `0..65535` |
| `CMSD_DISPENSE_SW` | Countermeasure dispenser switch | `0 BYPASS`, `1 ON`, `2 OFF` |
| `ECM_MODE_SW` | ECM mode switch | `0 XMIT`, `1 REC`, `2 BIT`, `3 STBY`, `4 OFF` |

`RWR_POWER_BTN` is also exported, but its pushbutton position is not used as a
substitute for actual RWR power; the dedicated power light is the candidate
state source. Likewise, `RADAR_SW = OPR` establishes only the commanded switch
position. It does not prove antenna operation, RWS/TWS display mode, a radarw
contact, designation, or lock.

Source: [official DCS-BIOS v0.11.5 Hornet module](https://github.com/DCS-Skunkworks/dcs-bios/blob/v0.11.5/Scripts/DCS-BIOS/lib/modules/aircraft_modules/FA-18C_hornet.lua).

## Setup and commands

From the `client` directory in the development environment:

```bash
uv run mara indications install "C:\\Users\\<you>\\Saved Games\\DCS"
uv run mara indications scan --first-id 0 --last-id 30
uv run mara indications watch --first-id 0 --last-id 30
uv run mara indications watch --first-id 0 --last-id 30 --diff
uv run mara indications experiments
uv run mara indications record radar-off --aircraft FA-18C_hornet --dcs-version <version>
uv run mara indications validate diagnostics/indication-recordings/radar-off
uv run mara indications replay diagnostics/indication-recordings/radar-off --diff
```

`install` is explicit and repeatable. It backs up a changed existing probe and
`Export.lua` before installing `Scripts/MARA/MARAIndications.lua`. Restart DCS
after installation. The default probe control port is `7779`; a developer can
change the client side with `MARA_INDICATION_PORT` only if the Lua constant is
changed to match.

The scanner prints empty responses because an empty indicator is evidence. A
missing UDP response is printed as `<NO RESPONSE>` and is not treated as an
empty display. The watcher polls at at most 10 Hz and the Lua side sends an
indicator only on its first sample or when its exact raw string changes. A
single request is capped at 64 indicator IDs, and abandoned watches expire
after five seconds without a local heartbeat.

Recordings are written to:

```text
diagnostics/indication-recordings/<scenario>/
    metadata.json
    events.jsonl
```

Each JSONL event preserves the raw string, indicator ID, source observation
time, local receipt time, sequence number, and explicit probe error. Metadata
includes the scenario, aircraft and DCS version when supplied, pinned DCS-BIOS
version, start/end time, configured indicator IDs, poll rate, and event count.
Known controlled scenario names also embed their experiment group and action in
metadata. The validator rejects malformed, oversized, timezone-ambiguous, or
out-of-range data before it can become a parser fixture. Replay preserves file
order and reports duplicate or out-of-order packet sequences rather than hiding
them, allowing later parsers to be tested against those conditions explicitly.

## Controlled experiment matrix

First run a broad scan, identify non-empty IDs, and narrow subsequent recordings
to those IDs. Keep one action per recording. Wait several seconds before and
after each transition so stable and changed states are both clear.

### Radar

Record separate scenarios for radar OFF, STBY, and OPR; A/A mode; RWS; TWS; one
contact; several contacts; designation; STT; lock acquired; lock lost; range
change; elevation change; shoot cue appearing; and shoot cue disappearing.

For every claimed field, establish whether it requires a particular page to be
visible and whether the value disappears on a page change. Do not equate a
designation with STT or an RWR lock with a radar lock.

### SA page

Record no tracks; friendly, hostile, unknown, and donor tracks; several tracks;
selected-track changes; range-scale changes; waypoint changes; a track leaving
range; and a disappearing contact.

Specifically inventory exported text, track identifiers, altitude, Mach,
symbols, coordinates, relative position, HAFU metadata, and other track
metadata. Absence of a graphical symbol in the raw string is not evidence for a
negative semantic state.

### RWR

Record power off/on; a search emitter appearing/disappearing; tracking; lock;
missile launch warning; multiple emitters; and priority changes. Compare
DCS-BIOS controls, indication strings, and dedicated cockpit lights. A generic
control transition must never generate a lock or launch event.

## Evidence promotion checklist

A row can move from `UNKNOWN` only when the recording captures:

1. the DCS and DCS-BIOS versions and exact indicator IDs;
2. a stable before state, the single controlled action, and a stable after state;
3. at least one repeat showing the same raw transition;
4. a negative/control case that does not produce the transition;
5. page-visibility and multiplayer/export-permission behavior;
6. a replay fixture with no inferred or synthesized fields.

Once evidence exists, copy a minimized, non-sensitive recording into the
replay-fixture tree and update this table with the source, status, reliability,
and fixture path. Only then should `FA18IndicationParser` and the normalized
`SituationEngine` be started.
