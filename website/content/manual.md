# Flight manual

MARA is a mission-aware voice copilot for Digital Combat Simulator. She listens only while you hold push-to-talk, follows F/A-18C cockpit state during the sortie, and speaks up when a deterministic rule calls for it. The early-access build currently supports the Hornet only.

> **Early-access note**
> MARA is still in qualification. Treat every callout as assistance—not as a replacement for the aircraft manual, your instruments, or your own judgement.

## Choose your setup

MARA has two installation types. The DCS Copilot client always runs on the gaming PC because it talks directly to DCS, handles push-to-talk, and plays MARA’s voice. The backend can run on that same PC or somewhere else.

| | All-in-one install | Split install |
| --- | --- | --- |
| **Where the backend runs** | On the DCS PC | On another PC, a LAN server, or a hosted server |
| **Setup** | Easiest; install the bundle and use the default local mode | Install the client on the DCS PC, run the backend elsewhere, then enter its URL in Settings |
| **Game-PC overhead** | Uses additional RAM and some CPU time for the backend and local voice | Only the thin DCS client runs on the game PC |
| **Best for** | Getting started quickly and keeping everything self-contained | Keeping as much work as possible away from DCS |

### All-in-one install (default)

Install `MARA-Setup-<version>.exe` and leave the backend mode set to **Local**. The desktop app starts and stops the bundled backend for you. This is the simplest option and does not require another machine.

The trade-off is straightforward: the backend, local database, and local voice service share the gaming PC with DCS. That means more RAM use and a small amount of CPU overhead. The exact amount depends on what MARA is doing, so we are not publishing a made-up performance number.

### Split install (lighter on the DCS PC)

Install the normal DCS Copilot client on the gaming PC, but run the standalone MARA backend on another Windows PC, a LAN server, or a hosted server. In Settings, change the backend mode to **Remote** and enter that backend’s URL.

The client still handles DCS-BIOS, cockpit data, the microphone, push-to-talk, and audio playback locally. The backend work—aircraft state, rules, checklists, database, voice pipeline, and AI calls—runs on the other machine. This is the better option if you want MARA’s game-PC footprint to stay small, at the cost of a little more setup and dependence on the network connection.

> **Which one should I use?**
> Start with all-in-one. Switch to a split install if you are short on RAM, want to keep background CPU work away from DCS, or already have a machine that can host the backend.

## Start here

The early-access client is a Windows application. Your access package includes the combined installer, the standalone backend package for split installations, and the service details you need.

1. Close DCS before running the installer.
2. Install **DCS Copilot** and allow setup to find your DCS Saved Games folder.
3. Let setup install or repair DCS-BIOS and update `Export.lua`.
4. Open DCS Copilot, choose your microphone and audio output, then bind push-to-talk.
5. Start DCS and load into the F/A-18C. MARA connects when cockpit data becomes available.

If DCS is installed in a non-standard location, choose the Saved Games folder in Settings. MARA keeps timestamped backups before changing an existing DCS-BIOS or `Export.lua` setup.

## Your first sortie

Use a simple cold-start or free-flight mission for the first run.

### 1. Check the status panel

Before entering the cockpit, confirm that the app can see DCS-BIOS, the backend, your microphone, and your selected push-to-talk input. An unavailable item should be fixed before takeoff.

### 2. Hold to talk

Hold your bound key or HOTAS button, speak, then release. MARA does not leave the microphone open between turns. Pressing push-to-talk also interrupts a callout that is already playing.

Try:

- “What needs my attention?”
- “Walk me through the next checklist.”
- “What phase of flight are we in?”

### 3. Let the cockpit lead

MARA receives changes from supported cockpit controls throughout the session. You do not have to narrate every switch position. If a value is missing or stale, the related rule is disabled instead of guessing.

## What MARA can do

### Cockpit awareness

MARA turns supported aircraft signals into a small, readable flight state. For the F/A-18C early-access build, this includes phase-of-flight awareness, selected system state, and deterministic caution rules.

Examples include master caution, gear overspeed, an open canopy while moving, parking brake use during taxi, taxi-light state, ejection-seat arming, and a refuelling probe left extended.

### Ground operations

MARA can guide a checklist, keep progress through interruptions, and report takeoff-readiness gates. Checklist progress is explicit: an item is completed because its required state was observed, not because a language model assumed it.

### In-flight assistance

Ask for concise status on fuel, navigation, defensive systems, landing configuration, and active warnings. Answers are limited to verified, supported state. MARA does not invent data for an unavailable sensor or cockpit signal.

### What is not ready yet

Radar-picture analysis, combat-awareness assistance, situational-awareness gap detection, and the full Spatial Coach experience are on the [roadmap](../roadmap/). Foundations for formation work, carrier approaches, and CASE I practice exist, but they are not part of the current early-access promise.

## Voice and controls

| Control | Behaviour |
| --- | --- |
| Push-to-talk | Hold to record a turn; release to send it. Also interrupts MARA. |
| Assistant mute | Stops current playback and suppresses later speech until toggled again. |
| Speech mode | Chooses how readily proactive callouts are spoken. |

Speech modes are deliberately simple:

- **Minimal** — only the most time-critical warnings.
- **Normal** — warnings plus useful operational advisories.
- **Coach** — the broadest proactive speech setting. This is separate from the planned Spatial Coach experience.

## Privacy boundary

MARA is designed around data minimisation. Raw cockpit telemetry stays in bounded session memory and is not written to account history. Push-to-talk bounds microphone capture; raw audio is not part of flight history.

Saved account information is separate from live aircraft state. Only information you explicitly ask MARA to remember, supported preferences, and small semantic flight summaries are persisted. Exercise recordings are opt-in.

MARA never uses a denied DCS export capability as if it were available. It does not restore hidden mission data through Tacview, cached coordinates, or another side channel.

## Troubleshooting

### MARA cannot see DCS

Close DCS, open the desktop app, and use the DCS setup repair action. Confirm that the selected Saved Games folder matches the DCS variant you actually launched.

### My HOTAS button is not detected

Reconnect the controller, reopen Settings, and use input learning again. The current Windows build supports standard controller buttons 1–32.

### MARA hears me but does not answer

Check the backend and audio-output indicators, then verify that assistant mute is off. A push-to-talk tone confirms when mute changes.

### Coach mode says unavailable

The current mission or multiplayer server may deny the required DCS export data. That is a capability restriction, not necessarily a connection failure.

## Early-access expectations

The first release is focused on Windows and the F/A-18C. Aircraft coverage, live multiplayer behaviour, and installer compatibility are being expanded through explicit validation—not assumed from simulator fixtures. MARA is planned to be released as open source.

When you report a problem, include the aircraft, mission type, DCS version, what the status panel showed, and the exact steps immediately before the issue. Do not include credentials or private tokens.
