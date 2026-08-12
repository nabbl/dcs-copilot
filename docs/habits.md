# Deterministic habit statistics

Habit statistics are calculated entirely on the backend. The backend
`FlightStatsManager` observes the same deterministic rule transitions as live
monitoring. No flight summary is ever sent from the client; habit accounting is
backend-internal.

## Backend calculation

`FlightStatsManager` observes the `RuleEngine` running in the cloud's
session-memory `AircraftStateStore`. For each flight it keeps only:

- the own-aircraft identifier;
- which allowlisted rules were evaluable from usable telemetry;
- how many times each covered rule activated.

At session end or aircraft slot change it creates a versioned internal summary.
A zero is meaningful only for a covered rule. Unavailable or stale telemetry
leaves the rule absent. Speech policy does not affect the statistic because it
observes rule transitions before publication or TTS decisions.

## Persistence

The backend stores one flight-summary record plus one row per covered rule,
scoped to the authenticated user. Records contain no raw telemetry value, phase
history, event text, audio, transcript, mission state, cockpit control, or
world/enemy data. Cloud insertion is idempotent by user and summary UUID.

## Habit answers

`get_pilot_habits` queries a bounded recent-flight window. It calculates:

- recent flights in the requested window;
- flights with usable coverage for the rule;
- covered flights where the rule activated;
- total activations.

The service emits a deterministic statement such as: "You've left the
refueling probe out in three of your last five Hornet flights." It uses that
wording only when all five flights have coverage; otherwise it explicitly says
how many recent flights had usable telemetry. The LLM is prompted to repeat the
returned sentence and must never derive a statistic from memory or generic
flight history.

Milestone 7 does not include Milestone 8 metering, entitlements, subscriptions,
device management, rate limiting, or operations monitoring.
