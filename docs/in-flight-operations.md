# MARA In-Flight Operations v1

Status: first implementation slice.

In-Flight Operations v1 gives MARA a deterministic handoff from takeoff to
flight and a small verified Hornet procedure corpus. Live state and procedural
knowledge remain separate: telemetry answers what the aircraft is doing now;
curated cards explain a supported procedure.

## Deterministic flight status

`get_flight_status` returns one bounded status object containing:

- physical flight phase and an operational stage (`DEPARTURE`, `EN_ROUTE`,
  `COMBAT`, `REFUELING`, or `ARRIVAL`);
- airspeed, MSL altitude, heading, and fuel telemetry with availability and
  staleness preserved;
- active-rule coverage, issue count, and highest active severity;
- a separate departure-cleanup gate.

The departure gate applies only after airborne state is positively observed
during `TAKEOFF` or `CLIMB`; it never prompts gear retraction on the takeoff
roll. It verifies gear up, flaps AUTO, and launch bar retracted. Known wrong
values make the result `BLOCKED`; missing or stale values make it `UNKNOWN`;
every item must be observed correct for `READY`. Outside airborne departure it
is `NOT_APPLICABLE`.

## Curated Hornet knowledge

`get_hornet_knowledge` serves small MARA-authored cards for these v1 topics:

- departure cleanup;
- TACAN navigation;
- waypoint navigation;
- coupled autopilot navigation;
- autopilot relief modes;
- carrier launch;
- CASE I carrier recovery;
- airfield VFR landing.

The source of record is Eagle Dynamics' English **DCS: F/A-18C Early Access
Guide**. The current source file has PDF creation date `2024-03-24` and is
pinned as SHA-256
`063873fac43245154bd772241fce89fe4985128cd962cb3e43fc9cefbc35d74c`.
The MARA corpus version is `fa18c-ed-2026.08.2`.

Every card includes its aircraft applicability, original summary, short steps,
cautions, official manual section and pages, source URL, document hash, and
review date. The cloud ships these structured cards; it does not ingest the
entire PDF into a vector database or ask the LLM to recall the manual.

For a question such as “How does a CASE I carrier landing look again?”, MARA
returns a compact pattern overview from the reviewed CASE I card. On an explicit
request to be walked through it, MARA presents one card step at a time and waits
for the pilot to request the next step. This conversational guide does not mark
steps complete and cannot verify ship position, deck status, pattern geometry,
IFLOLS, or LSO direction. Telemetry-aware carrier approach coaching remains a
future safety milestone.

Chuck's Guide is not included in the shipped corpus. It is an excellent pilot
learning resource and can be used by maintainers as a cross-check, but MARA
should not copy, embed, or redistribute it without explicit reuse permission.
If permission is obtained later, it should be represented as an independently
pinned secondary source rather than silently mixed into the ED-derived cards.

## Expansion policy

A new source-verified procedural topic requires a reviewed card, an exact source
section, a pinned source revision, and tests. If no curated card exists, MARA
still answers directly from its best Hornet or general aviation knowledge. It
does not refuse solely because the corpus lacks the topic, but it must not invent
a citation or represent the fallback as source-verified. Live cockpit claims
remain tool-backed. Combat employment is intentionally outside this milestone.

The official guide does not contain a complete aerial-refueling procedure, so
an AAR card is intentionally deferred until a suitable authoritative source can
be pinned and reviewed.
