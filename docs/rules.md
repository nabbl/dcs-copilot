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
| `FA18_PARKING_BRAKE_TAXI` | ADVISORY | WOW, parking brake engaged, IAS at least 5 kt | Brake released, airborne, or IAS below 2 kt | 2 / 0.5 s | 45 s |
| `FA18_EJECTION_SEAT_NOT_ARMED` | WARNING | Seat SAFE during TAXI or an airborne phase | Seat armed; leaving applicable phases disables it | 2 / 0.25 s | 120 s |

Cooldown controls whether a new activation is eligible for future proactive
notification; it does not hide a currently active issue. Speech policy and
acknowledgement are intentionally deferred to Milestone 5.

The 250-knot gear threshold follows the Hornet landing procedure in the Eagle
Dynamics guide, which calls for gear and flaps down at 250 knots. The cockpit
signals are the adapter's verified `MASTER_CAUTION_LT`, gear lights and lever,
`CANOPY_POS`, `EMERGENCY_PARKING_BRAKE_ROTATE`, and `EJECTION_SEAT_ARMED`
exports. Live behavior still requires the validation matrix in
`docs/multiplayer-validation.md`; automated fixtures are not evidence of
multiplayer or Integrity Check compatibility.

## Replay format

Each non-comment JSONL line is a complete normalized snapshot. Values provided
in `fields` are available by default; omitted fields are unavailable. A value
may instead be an object with `value`, `available`, `stale`, `updated_at`, and
`source` keys. `flight_phase` is optional—when omitted, replay runs the phase
detector.

```json
{"timestamp":3,"aircraft":"FA-18C_hornet","fields":{"indicated_airspeed":260,"gear_position":"DOWN","weight_on_wheels":false}}
```

Run a synthetic fixture with:

```bash
uv run dcs-copilot replay client/tests/fixtures/replay/airborne-alerts.jsonl
```
