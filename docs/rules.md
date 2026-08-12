# Deterministic rules

Rules consume only normalized own-aircraft telemetry. They never resolve raw
DCS-BIOS addresses and never infer a value that is missing, stale, or restricted
by a multiplayer server. If a required value becomes unusable, the rule is
disabled immediately and any active issue is removed with a `DISABLED`
transition. `RESOLVED` is reserved for a condition that was observed clearing.

## Initial F/A-18C rules

| Rule | Severity | Activation | Clear hysteresis | On/off debounce | Cooldown |
| --- | --- | --- | --- | --- | --- |
| `FA18_MASTER_CAUTION` | WARNING | Master Caution light on | Light off | 0.25 / 0.5 s | 30 s |
| `FA18_GEAR_OVERSPEED` | WARNING | Airborne, gear down or in transit, IAS at least 250 kt | On ground, gear up, or IAS below 240 kt | 1 / 1 s | 30 s |
| `FA18_CANOPY_OPEN_MOVING` | WARNING | Canopy not closed and IAS at least 20 kt | Canopy closed or IAS below 10 kt | 1 / 0.5 s | 30 s |
| `FA18_PARKING_BRAKE_TAXI` | ADVISORY | WOW, parking brake engaged, ground speed at least 5 kt | Brake released, airborne, or ground speed below 2 kt | 2 / 0.5 s | 45 s |
| `FA18_TAXI_LIGHT_OFF` | ADVISORY | TAXI phase, WOW, taxi light off, ground speed at least 3 kt | Light on, stopped, airborne, or leaving TAXI | 5 / 0.5 s | 120 s |
| `FA18_EJECTION_SEAT_NOT_ARMED` | WARNING | Seat SAFE during TAXI or an airborne phase | Seat armed; leaving applicable phases disables it | 2 / 0.25 s | 120 s |
| `FA18_REFUELING_PROBE_LEFT_OUT` | ADVISORY | Probe extended during climb, cruise, combat, approach, or landing | Probe retracted; entering another phase disables it | 2 / 0.25 s | 60 s |

Cooldown controls whether a new activation is eligible for proactive
notification; it does not hide a currently active issue.

## Event and speech policy

Every rule transition enters the bounded backend event history. An activation
and its later resolution or disablement share an event ID. Only semantic fields
are eligible for the proactive speech path: rule ID, severity, aircraft, phase,
concise message, and the rule's bounded data object.

Speech policy is enforced backend-side using the account's chatter preference,
defaulting to `NORMAL`:

- `MINIMAL`: only rules explicitly marked for minimal speech, generally
  time-critical launch, gear, oxygen, seat, and hook warnings;
- `NORMAL`: rules marked for normal speech, including the taxi-light,
  parking-brake, and refueling-probe advisories;
- `COACH`: every cooldown-eligible activation, including INFO.

Rules explicitly marked non-proactive remain available in backend issue/history
diagnostics but are never spoken. Eligible activations use cloud TTS; PTT
suppresses or interrupts them. No duplicate offline client rule engine exists.

The 250-knot gear threshold follows the Hornet landing procedure in the Eagle
Dynamics guide, which calls for gear and flaps down at 250 knots. The cockpit
signals are the adapter's verified `MASTER_CAUTION_LT`, gear lights and lever,
`CANOPY_POS`, `EMERGENCY_PARKING_BRAKE_PULL` with rotation fallback,
`LDG_TAXI_SW`, and
`EJECTION_SEAT_ARMED`
exports. Live behavior still requires the validation matrix in
`docs/multiplayer-validation.md`; automated fixtures are not evidence of
multiplayer or Integrity Check compatibility.

Ground movement uses a backend position delta from DCS-BIOS CommonData rather than
wind-affected indicated airspeed. Coordinates are not placed in normalized
state or transmitted beyond the telemetry stream.
