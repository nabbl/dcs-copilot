# Deterministic habit statistics

Milestone 7 records narrow semantic outcomes at the end of each locally
observed flight. It does not upload DCS-BIOS frames, cockpit snapshots, or a
telemetry timeseries.

## Local calculation

`FlightStatsManager` observes the existing `RuleEngine`. For each flight it
keeps only:

- the own-aircraft identifier;
- which allowlisted rules were evaluable from usable telemetry;
- how many times each covered rule activated.

At disconnect, aircraft change, replay completion, or shutdown, it emits a
versioned `flight.summary`. A zero is meaningful only for a covered rule.
Unavailable or stale telemetry leaves the rule absent. Speech policy does not
affect the statistic because it observes rule transitions before publication
or TTS decisions.

## Delivery and persistence

The client retains a bounded in-memory set of unacknowledged summaries. It
resends them when the authenticated WebSocket reconnects. The cloud validates
the fixed rule allowlist, accepts uploads only for signed-in users, and uses the
pair of user ID and summary UUID as an idempotency key. A duplicate is
acknowledged without changing any count.

The database stores one flight-summary record plus one row per covered rule.
Rows are user-scoped. They contain no raw value, phase history, event text,
audio, transcript, mission state, cockpit control, or world/enemy data.

## Habit answers

`get_pilot_habits` queries a bounded recent-flight window. It calculates:

- recent flights in the requested window;
- flights with usable coverage for the rule;
- covered flights where the rule activated;
- total activations.

The service emits a deterministic statement such as: “You've left the
refueling probe out in three of your last five Hornet flights.” It uses that
wording only when all five flights have coverage; otherwise it explicitly says
how many recent flights had usable telemetry. The LLM is prompted to repeat the
returned sentence and must never derive a statistic from memory or generic
flight history.

Milestone 7 does not include Milestone 8 metering, entitlements, subscriptions,
device management, rate limiting, or operations monitoring.
