# MARA release qualification checklist

These checks need a real Windows/DCS/audio/network environment. They are final
release qualification, not prerequisites for automated development validation.

## Clean installation and lifecycle

- Install `MARA-Setup-<version>.exe` on clean Windows 10 and 11 x64 machines
  without Python, uv, Node.js, Docker, Git, or build tools.
- Confirm fresh launch selects Local, starts `MaraBackend.exe`, reaches Ready,
  and writes only below `%LOCALAPPDATA%\MARA`.
- On a fresh profile, confirm Settings first shows Kokoro verification/download
  progress and a separate OpenAI key/access state. Confirm Start MARA remains
  disabled until both are operational and that the displayed blocker is specific.
- Use Open logs and confirm it opens `%LOCALAPPDATA%\MARA\logs` containing
  `backend.log` and `backend-process.log`, including useful model-download or
  startup errors without credentials.
- Confirm Windows Credential Manager contains the OpenAI credential and neither
  config nor logs contain it.
- Quit MARA and confirm its child backend exits; start a backend independently
  and confirm quitting MARA does not stop it.
- Crash the child backend repeatedly and confirm bounded recovery plus the
  Restart Backend action.
- Validate upgrade from a prior public build preserves a custom hosted URL and
  refresh credentials; validate uninstall leaves user data intentionally.

## DCS host integration

- Validate default and relocated DCS/DCS.openbeta Saved Games folders.
- Validate DCS-BIOS install/repair, existing multi-plugin `Export.lua`, backups,
  aircraft detection, live ownship telemetry, and the indication probe.
- Validate FA-18C Coach rules/checklists with DCS connected and clean behavior
  when DCS is absent or disconnects.
- Validate Integrity Check and multiplayer restrictions using the separate
  multiplayer matrix.

## Voice and hardware

- Validate keyboard and representative HOTAS PTT/mute inputs, device removal,
  microphone capture, interruption, speaker playback, and audio-device changes.
- Validate first-use Kokoro model provisioning, progress/failure behavior,
  offline reuse, voice quality, latency, and Windows Defender scanning impact.
- Validate OpenAI STT/LLM using a real user-provided key, key replacement, key
  deletion, invalid/revoked keys, and absence of paid calls in automated tests.

## Remote/hosted deployment

- Connect from another physical LAN PC over `ws://192.168.x.x:47100`, with a
  narrowly scoped firewall rule, account registration, reconnect, and latency.
- Switch Local to a valid remote backend and confirm the owned local backend is
  stopped only after compatibility succeeds; repeat with an invalid/incompatible
  remote and confirm Local remains selected and running.
- Switch Remote to Local and confirm readiness completes before the live client
  changes endpoints.
- Validate hosted Docker/CapRover deployment behind HTTPS/WSS, PostgreSQL,
  credential rotation, backups, and production authentication controls.

## Installer and release operations

- Code-sign the client, CLI, backend, and installer; verify trusted timestamp,
  SmartScreen/Defender behavior, artifact SHA-256 values, repair, and uninstall.
- Confirm no broad Windows Firewall rule, Windows service, or login autostart is
  created by default.
- Inspect third-party license payloads and Kokoro model license attribution.
