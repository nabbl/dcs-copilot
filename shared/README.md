# DCS Copilot shared protocol

Standard-library JSON control and binary media envelopes for protocol version
2, including strict schemas for decoded DCS-BIOS catalogs, initial snapshots,
and changed-value deltas.

The package contains transport-neutral validation only. Aircraft
normalization, phases, rules, checklists, events, habits, speech policy, and
Mara tools belong to the cloud package. Numeric DCS-BIOS addresses, account
credentials, cloud memory objects, and business logic never enter this package.
The package contains no transport implementation or business logic and is small
enough to reimplement in a future native client.
