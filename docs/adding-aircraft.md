# Adding an aircraft adapter

Aircraft adapters translate symbolic DCS-BIOS controls into the small normalized
`AircraftState`; they never contain addresses. A new adapter should be added only
after its controls and value behavior have been checked in the installed
DCS-BIOS control reference and, where needed, in a live cockpit.

## Interface

Implement `AircraftAdapter` with an `aircraft_names` set and a `normalize()`
method returning `PartialAircraftState`. Construct a `ControlReader` from the
registry and incoming `DcsBiosState`. The reader provides decoded values with
source, timestamp, availability, and staleness. Register the adapter in
`AircraftStateStore`.

Never silently substitute a different control when the intended one is missing.
Composite fields must be unavailable unless every required component is
available and semantically valid. Keep module-specific identifiers inside the
adapter; rules consume normalized names only.

## Hornet v1 mapping

| Normalized field | DCS-BIOS source | Notes |
| --- | --- | --- |
| IAS | `CommonData/IAS_US_INT` | Requires advancing CommonData model time |
| Ground speed | Local delta of `CommonData/LAT_*` and `LON_*` | Coordinates remain client-local and are not exposed; requires advancing model time |
| MSL altitude | `CommonData/ALT_MSL_FT` | Requires advancing CommonData model time |
| Heading | `CommonData/HDG_DEG_MAG` | Magnetic degrees; CommonData health-gated |
| Gear | `GEAR_LEVER` plus three `FLP_LG_*_GEAR_LT` | Down requires all three lights; up requires lever-up/dark lights to remain stable for three seconds |
| Flaps | `FLAP_SW` | Verified positions: AUTO, HALF, FULL |
| Canopy | `CANOPY_POS` | Scaled 0–1; closed/open thresholds preserve transit |
| Master Arm | `MASTER_ARM_SW` | 0 SAFE, 1 ARM |
| Total fuel | `IFEI_FUEL_UP` plus `IFEI_T` | Pounds; available only when upper legend is `T` |
| Master Caution | `MASTER_CAUTION_LT` | Boolean light state |
| Parking brake | `EMERGENCY_PARKING_BRAKE_PULL` with rotate fallback | Pulled means engaged; rotate fallback is 0 emergency, 1 parking, 2 release |
| Battery | `BATTERY_SW` | 0 on, 1 off, 2 override |
| APU ready | `APU_READY_LT` | Boolean indicator |
| Speed brake | `EXT_SPEED_BRAKE` | Physical position scaled 0–1 |
| Refueling probe | `EXT_REFUEL_PROBE` | Physical extension; true above 10% |
| Hook | `EXT_HOOK` | Physical position; down above 50% |
| WOW | `EXT_WOW_NOSE/LEFT/RIGHT` | Available only when all three bits are available |
| Engine RPM | `IFEI_RPM_L/R` | Numeric IFEI N2 percentage strings |
| Throttles | `INT_THROTTLE_LEFT/RIGHT` | Position scaled 0–1 |

The IFEI upper counter is normally total fuel, but the pilot can cycle it to
individual tank pairs. The `T` legend guard prevents a tank quantity from being
misreported as aircraft total. This behavior follows the Eagle Dynamics Hornet
guide's IFEI description.

## Required tests

For each mapped field, test normal values, unavailable inputs, stale inputs, and
invalid strings/enums. Composite fields need partial-input and transition cases.
Add phase tests only for inferences supported by the new aircraft's verified
telemetry; otherwise allow `UNKNOWN`.
