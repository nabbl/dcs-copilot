# Multiplayer validation

No live DCS environment has been tested yet. Do not describe this build as
"Integrity Check safe" until the matrix below is completed on the target PC.

| Environment | DCS-BIOS controls | CommonData | IAS | Ground speed | Altitude | Aircraft detection | Warning lights | Module switches | IC passes | Stale/blocked fields | Evidence/date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Single-player mission | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | N/A | Unknown | Pending |
| Multiplayer, permissive exports | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Unknown | Pending |
| Multiplayer, restrictive exports | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Unknown | Pending |
| Multiplayer with Integrity Check | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Not tested | Unknown | Pending |

For every run, record the DCS version, DCS-BIOS version/commit, aircraft/module,
server export settings if known, and an anonymized diagnostics capture. A field
that does not update must be marked unavailable; it must not be inferred from a
different source merely to make a rule run.

## Milestone 1 live rule acceptance

For each environment above, use `dcs-copilot watch` and safely exercise each
condition in a controlled mission. Record whether every issue activates after
its documented debounce, clears after its documented hysteresis, and becomes
`DISABLED` rather than remaining active when its required export disappears:

- Master Caution on/off.
- Gear down through 250 knots, then gear up or speed below 240 knots.
- Canopy not closed while moving, then closed.
- Parking brake engaged while rolling on the ground, then released.
- Ejection seat SAFE during taxi, then ARMED.

Do not intentionally create unsafe flight conditions merely to complete this
matrix. Replay coverage is the fallback when a condition cannot be exercised
safely; record that it was not live-tested.
