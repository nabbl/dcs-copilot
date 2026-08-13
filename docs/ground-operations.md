# MARA Ground Operations v1

Status: first implementation slice.

Ground Operations v1 makes MARA's primary journey the transition from cockpit
entry through takeoff. It deliberately keeps physical movement, checklist
progress, and readiness as separate deterministic concepts.

## Implemented in the first slice

The backend `GroundOpsCoordinator` reports these semantic phases:

- `COLD_START`
- `ENGINE_START`
- `PRE_TAXI`
- `READY_FOR_TAXI`
- `TAXI`
- `CARRIER_LAUNCH`
- `TAKEOFF_ROLL`
- `IN_FLIGHT`
- `POST_LANDING`
- `UNKNOWN`

The coordinator also returns independent before-taxi and takeoff-readiness
reports. Each report is one of:

- `READY`: every required item was positively verified;
- `BLOCKED`: at least one usable value is in a known unsafe or incomplete state;
- `UNKNOWN`: nothing is known wrong, but telemetry, pilot confirmation, or
  operation context is missing;
- `NOT_APPLICABLE`: the takeoff gate was requested after leaving the ground.

`get_ground_ops_status` exposes the current phase and both readiness summaries.
`get_takeoff_readiness` performs a final `LAND`, `CARRIER`, or conservative
`AUTO` gate. `AUTO` resolves to carrier only after the deterministic carrier
launch signal is active; it does not silently guess a land takeoff.

The Hornet takeoff gate currently verifies flaps, landing gear, hook,
speedbrake, Master Arm, ejection seat, OBOGS, canopy, takeoff-trim observation,
wings, Master Caution, flight-controls confirmation, and the operation-specific
launch-bar position.

## Guided checklist lifecycle

MARA now advertises all backend guided-checklist tools to the voice model. A
guide defaults to the checklist's configured target stage, which is `BEFORE
TAXI` for the Hornet startup checklist. The model can start or resume a guide,
request the next unresolved item, record an explicit pilot confirmation, and
stop spoken guidance.

Observed cockpit progress is independent of whether spoken guidance is active.
Stopping the guide preserves progress; a new cockpit epoch resets it.

Checklist items opt into historical latching individually. The parking brake is
latched once it was verified during pre-start, so releasing it for taxi does not
regress that step. Live requirements such as battery and Master Arm are not
latched and can become incomplete again if their state changes.

Pilot confirmation is deliberately scoped to the current unresolved item. When
the pilot explicitly reports a visible or physical state, such as the APU READY
light being illuminated, MARA records either `pilot_confirmation` for a manual
item or `pilot_override` for a telemetry-verifiable item and advances. It cannot
confirm a future item or infer confirmation from silence or implication. The
first inherently manual Hornet item is the before-taxi flight-controls check.

## Alignment boundary

Cockpit-only telemetry does not establish a land aircraft's position relative
to runway geometry. MARA therefore reports land-runway alignment as unconfirmed
and relies on an explicit pilot statement plus a `LAND` takeoff-readiness call.
It may positively report the carrier-launch state only when the deterministic
launch-bar/carrier signal is active.

## Safety invariants

- Active issues and readiness are separate; no active issues never means ready.
- `READY` requires positive verification of every gate.
- Stale and unavailable values remain unknown.
- The LLM phrases deterministic results but never calculates readiness.
- A checklist override requires explicit pilot confirmation of the current item
  and retains its verification source for auditability.
- Pilot overrides do not rewrite telemetry or suppress independent live safety
  warnings.
- Land-runway alignment is not inferred from heading, speed, or throttle alone.

## Remaining Ground Operations v1 work

- local deterministic critical-warning earcons or fixed phrases during cloud
  outages;
- live runtime health and readiness reporting in the desktop UI;
- richer sourced Hornet startup, navigation, and mission-configuration items;
- explicit pause, repeat, defer, and skip semantics for guided checklists;
- end-to-end voice journey fixtures for interrupted and resumed procedures;
- live single-player and multiplayer validation on Windows/DCS;
- broader coverage in the grounded, versioned aircraft knowledge source begun
  in [In-Flight Operations v1](in-flight-operations.md).
