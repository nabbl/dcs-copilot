# MARA spatial-coaching integration

Status: proposed integration contract; Milestones 1 and 2 implemented first.

## Existing architecture

The repository does not currently have a dedicated Coach subsystem. The existing
`COACH` value is a proactive-speech policy level, not an exercise engine. The
relevant runtime boundaries are:

- the Windows client passively acquires DCS-BIOS cockpit data and owns DCS
  `Export.lua` installation, audio, and transport;
- the shared package defines bounded, versioned wire messages without product
  logic;
- the cloud owns normalized state, deterministic rules and events, session
  state, Pipecat, tool execution, speech policy, account memory, and semantic
  flight summaries;
- the existing replay path is a local development replay for raw cockpit
  indications, not a flight or exercise replay system;
- raw telemetry is kept in bounded session memory and raw time series are not
  persisted.

Spatial Coach will extend those boundaries instead of creating another
assistant or voice pipeline.

## Target data flow

```text
DCS-BIOS cockpit data -------------------+
                                         |
DCS Export capability + selected data ---+--> normalized observations
                                         |           |
offline replay --------------------------+           v
                                                  spatial engine
                                                        |
                                                        v
                                              Coach exercise engine
                                                        |
                                  semantic feedback/debrief/tool results
                                                        |
                                                        v
                                             existing Pipecat + MARA voice
```

The live DCS Export provider belongs in the client because it talks to DCS. It
must call `LoIsObjectExportAllowed()` and transmit its result as the
authoritative world-object capability. It may select a requested lead or carrier
locally, but it must never send the complete world-object collection to the
cloud or the language model. The provider must not use Tacview, sensors, mission
state, or cached coordinates to restore a capability denied by DCS.

Normalized models, spatial math, exercise state, speech eligibility, statistics,
and replay execution belong in the cloud `dcs_copilot_cloud.coach` package. This
keeps geometry deterministic and next to the existing backend rule, event, and
tool layers. Pipecat receives only bounded semantic Coach results.

## Package responsibilities

```text
cloud/dcs_copilot_cloud/coach/
    capabilities.py       authoritative DCS flags and derived Coach flags
    observations.py       sourced, timestamped ownship/reference observations
    providers/             live/replay normalized provider interfaces
    spatial/               shared vectors, transforms, and relative geometry
    exercises/             formation, carrier approach, and CASE I state machines
    speech.py              hysteresis and cooldown policy
    replay.py              normalized exercise JSONL reader/writer
    tools.py               bounded high-level Coach tool executor
```

Milestone 1 introduces `capabilities.py`. Its state is closed by default. A
single update derives every higher-level capability and publishes a transition.
When `world_object_export` changes from true to false, the transition is marked
as permission loss. Future reference registries and exercise coordinators must
subscribe to that transition and synchronously clear external objects, stop
dependent exercises, and suppress relative observations.

Milestone 2 introduces the dependency-free `spatial` package. DCS local
coordinates are treated as `x = north/forward at zero heading`, `y = up`, and
`z = east/right at zero heading`. One transform produces the common
forward/right/up frame used by every exercise. Closure is positive when range
is decreasing.

## Integration with current services

- `AircraftStateStore` remains the cockpit/own-aircraft semantic store. A
  normalized ownship provider will adapt its sourced values plus permitted DCS
  Export pose data into `OwnshipState`; spatial exercises will not consume raw
  store keys.
- A session-scoped Coach coordinator will be created beside
  `AircraftStateStore` in the realtime app. Aircraft epoch reset, disconnect,
  and session end will reset both stores.
- Coach tools will use the same backend-internal callback used by current
  aircraft and account tools. The allowlist will expose capabilities, exercise
  lifecycle, semantic feedback, and debriefs only.
- Coach speech will use the existing interruptible TTS path. The exercise engine
  decides deterministic feedback and the Coach speech policy decides when it is
  eligible; the LLM may phrase debrief facts but never calculate geometry or
  statistics.
- Diagnostics will render the capability snapshot. A denied DCS permission is
  `UNAVAILABLE`, not an error, and existing cockpit/procedure Coach behavior
  remains available when cockpit telemetry is present.
- Exercise recordings will contain only normalized ownship, the selected
  reference, capability state, and derived exercise values. They will not be
  written to account memory or the existing generic flight-session table.

## Permission invariants

1. `world_object_export` comes only from `LoIsObjectExportAllowed()` for live
   DCS sessions.
2. Formation, CASE I, and carrier-approach geometry require both ownship export
   and world-object export.
3. Live Tacview data cannot affect those capability flags.
4. A false or missing flag means unavailable; there is no optimistic default.
5. Permission loss invalidates selected external objects before any subsequent
   exercise update.
6. Stale ownship or reference observations pause calculations rather than
   combining old and current data.

## Incremental delivery

This change implements only Milestone 1 (the explicit capability model and
status snapshot) and Milestone 2 (tested spatial primitives). Live Lua export,
wire schemas, providers, reference selection, exercises, voice tools,
diagnostics UI, and replay are deliberately left behind the interfaces above so
they can be added in the requested order without weakening the permission
boundary.
