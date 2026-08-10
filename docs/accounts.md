# Accounts and memory

Milestone 6 keeps identity, persistence, and memory in the cloud. The thin
client receives DCS Copilot credentials; it never receives an OpenAI credential
and never hosts the account database.

## Authentication flow

The cloud exposes HTTP operations under `/v1/auth`:

- `POST /register` creates a user and returns an access/refresh pair;
- `POST /token` verifies email/password credentials and returns a new pair;
- `POST /refresh` rotates a valid refresh credential;
- `POST /logout` revokes one refresh credential;
- `GET /me` validates a bearer access token and returns its user/device IDs.

Passwords are stored as salted scrypt hashes. Access tokens are HS256-signed,
audience/issuer checked, expire after 15 minutes by default, and are bound to
the device ID used during login. Refresh tokens are opaque random credentials.
Only their SHA-256 hashes are stored, and every successful refresh revokes the
old token before issuing a new one. A replayed, expired, revoked, or wrong-device
refresh token fails closed.

The realtime WebSocket accepts the signed access token in the existing
`authenticate` control. `DCS_COPILOT_DEV_TOKEN` remains an explicit localhost
development escape hatch and has no account identity, so it cannot read or
write memories. Set it to an empty value for a service deployment. Rate
limiting, device-management UI, entitlements, and operations monitoring belong
to Milestone 8 and are not claimed here.

## Database

Set `DCS_COPILOT_DATABASE_URL` to one of:

```text
sqlite+aiosqlite:///./dcs-copilot.db
postgresql+asyncpg://user:password@host/database
```

SQLite is for local development and tests. PostgreSQL is the production
backend. The initial milestone creates missing tables on startup; a production
deployment should place schema rollout under its normal migration/release
process before accepting customer traffic.

The schema contains users, hashed refresh credentials, explicit pilot
memories, allowlisted aircraft preferences, and semantic flight sessions. A
flight stores the user, device ID, client session ID, optional aircraft name,
start time, and end time. It does not store raw DCS-BIOS frames, cockpit
snapshots, audio, event statistics, mission state, enemy/world state, or
inferred habits.

## Cloud account tools

Pipecat advertises cloud account tools separately from local aircraft tools:

```text
get_pilot_memories
remember_pilot_fact
forget_pilot_fact
get_aircraft_preferences
set_chatter_level
get_flight_history
```

The executor binds every call to the authenticated user. Tool names and
arguments are allowlisted; keys use bounded lowercase `snake_case`, values are
bounded JSON scalars, queries return at most 20 records, and flight results omit
device and client identifiers. `remember_pilot_fact` is prompted for explicit
pilot requests only. Missing memory remains missing—the LLM is instructed never
to invent it.

Example development request:

```bash
curl -X POST http://127.0.0.1:8000/v1/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"pilot@example.com","password":"choose-a-long-password","device_id":"gaming-pc"}'
```

Place the returned short-lived `access_token` in
`DCS_COPILOT_ACCESS_TOKEN`. The refresh endpoint returns a rotated access and
refresh pair for the account client or launcher to retain securely.

## Milestone boundary

Milestone 6 does not calculate habits. Flight history is factual session
metadata only. Uploading deterministic end-of-flight statistics and deriving
observed-session habit counts is Milestone 7 work and is deliberately absent.
