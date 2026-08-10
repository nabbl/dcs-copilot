# DCS Copilot shared protocol

Standard-library JSON control and binary media envelopes for protocol version
1, including strict schemas for the four versioned read-only aircraft tools.
It also validates versioned semantic aircraft events used for proactive speech.
Versioned session metadata is limited to the current own-aircraft identifier;
account credentials and cloud memory objects never enter this package.
The package contains no transport implementation or business logic and is small
enough to reimplement in a future native client.
