# MARA spatial-coaching integration

Status: implemented integration contract; Milestones 1 through 8 complete.

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
    models.py             sourced, timestamped ownship/reference observations
    providers/            permission-gated live normalized observation store
    spatial/               shared vectors, transforms, and relative geometry
    exercises/            state machines, standards, hysteresis, and cooldowns
    replay.py              normalized exercise JSONL reader/writer
    tools.py               bounded high-level Coach tool executor
```

Milestone 1 introduces `capabilities.py`. Its state is closed by default. A
single update derives every higher-level capability and publishes a transition.
When `world_object_export` changes from true to false, the transition is marked
as permission loss. The reference registry and exercise coordinator subscribe
to that transition and synchronously clear external objects, stop dependent
exercises, and suppress relative observations.

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
- Explicit opt-in exercise recordings contain only normalized ownship, the
  selected reference, and capability state. Replay derives exercise values;
  neither recordings nor samples are written to account memory or the existing
  generic flight-session table.

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

## Delivered milestones

The implementation now includes the explicit capability model, shared spatial
math, permission-gated DCS provider, selected reference registry, configurable
left/right echelon exercises, moving-carrier approach geometry and trends,
ordered CASE I segmentation, deterministic statistics/debriefs, normalized
JSONL replay, high-level MARA tools, existing-pipeline speech, and diagnostics.
Live validation remains intentionally separate from implementation and must use
the multiplayer matrix before making Integrity Check compatibility claims.
