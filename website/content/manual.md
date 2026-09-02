# Flight manual

MARA is a mission-aware voice copilot for Digital Combat Simulator. She listens only while you hold push-to-talk, follows F/A-18C cockpit state during the sortie, and speaks up when a deterministic rule calls for it. The early-access build currently supports the Hornet only.

> **Early-access note**
> MARA is still in qualification. Treat every callout as assistance—not as a replacement for the aircraft manual, your instruments, or your own judgement.

## Before you install

The current Windows build expects the following:

- **A 64-bit Windows PC.** Windows 10 and 11 are the current validation targets. The packaged installer includes the client and backend, so you do not need to install Python.
- **DCS World and the F/A-18C.** The early-access aircraft integration is for the Hornet. Launch DCS at least once so it creates a `Saved Games\DCS`, `DCS.openbeta`, or `DCS.openalpha` folder.
- **A working Windows default microphone and audio output.** The current desktop app uses the devices selected as the Windows defaults; it does not yet have separate microphone or speaker selectors.
- **A push-to-talk control.** Use a keyboard function key from F1–F24, or a button from 1–32 on a controller exposed through the Windows joystick API. MARA mute needs a different key or button.
- **Internet access.** Setup downloads DCS-BIOS from GitHub. A local backend also downloads roughly 340 MB of Kokoro voice files on first launch and needs ongoing access to the OpenAI API.
- **An OpenAI API key for a local or self-hosted backend.** The key must have working API access. MARA checks it without running inference and reports missing, rejected, rate-limited, or unreachable access separately.
- **Enough local storage for MARA’s files.** In local mode, allow roughly 340 MB for the voice model in addition to the installed application, local database, and logs.

> **Set your Windows audio defaults first**
> Choose the microphone and speakers or headset you want to use in Windows before starting MARA. The current app does not provide its own audio-device picker.

The installer is per-user and does not request administrator privileges. The early-access installer is currently unsigned, so Windows SmartScreen may show a warning. Use only a package supplied by the project and verify it against the published `checksums.txt` file.

## Choose your setup

MARA has two installation types. The DCS Copilot client always runs on the gaming PC because it talks directly to DCS, handles push-to-talk, and plays MARA’s voice. The backend can run on that same PC or somewhere else.

| | All-in-one install | Split install |
| --- | --- | --- |
| **Where the backend runs** | On the DCS PC | On another PC, a LAN server, or a hosted server |
| **Setup** | Easiest; install the bundle and use the default local mode | Install the client on the DCS PC, run the backend elsewhere, then enter its URL in Settings |
| **OpenAI API key** | Bring your own key and enter it in MARA Settings | Configure the key on your self-hosted backend; do not enter it on the DCS PC. A managed hosted service handles this for you |
| **Account** | No MARA account required | Remote mode asks you to sign in or create an account on that backend |
| **First voice download** | Roughly 340 MB on the DCS PC | Downloaded and cached on the backend machine |
| **Game-PC overhead** | Uses additional RAM and some CPU time for the backend and local voice | Only the thin DCS client runs on the game PC |
| **Best for** | Getting started quickly and keeping everything self-contained | Keeping as much work as possible away from DCS |

### All-in-one install (default)

Install `MARA-Setup-<version>.exe` and leave the backend mode set to **Local**. The desktop app starts and stops the bundled backend for you. This is the simplest option and does not require another machine.

> **Local mode requires your own OpenAI API key**
> MARA uses OpenAI for speech recognition and assistant responses. [Create or manage an API key](https://platform.openai.com/api-keys), then open MARA Settings and enter it in the secure local-backend API key field. MARA stores the key in Windows Credential Manager—not in its configuration file—and does not send it to a remote MARA server. OpenAI API usage belongs to the OpenAI account and project behind that key.

Treat the key like a password. Do not share it, paste it into a bug report, or add it to a configuration file.

On the first start, keep MARA open while the Settings page downloads and verifies the Kokoro voice files. Progress appears on the **Kokoro voice** status card. The backend is not ready until both Kokoro and the OpenAI API checks pass.

The trade-off is straightforward: the backend, local database, and local voice service share the gaming PC with DCS. That means more RAM use and a small amount of CPU overhead. We do not have a reliable RAM or CPU minimum yet, so we are not publishing a made-up performance number.

### Split install (lighter on the DCS PC)

Install the normal DCS Copilot client on the gaming PC, but run the standalone MARA backend on another Windows PC, a LAN server, or a hosted server. The supplied standalone ZIP is built for 64-bit Windows. In Settings, change the backend mode to **Remote**, enter the backend URL, and use **Test connection**.

If you run your own remote backend, configure the OpenAI API key on the **backend machine**. The DCS client does not need the key. If you connect to a managed hosted MARA service, that service handles the backend credentials for you.

For a private LAN, the backend host must allow the chosen port—47100 by default—through a narrowly scoped firewall rule. MARA does not create that rule automatically. Use HTTPS/WSS through a trusted reverse proxy for a backend exposed outside a private network. The desktop also checks that the backend API version matches the client before it will start.

The client still handles DCS-BIOS, cockpit data, the microphone, push-to-talk, and audio playback locally. The backend work—aircraft state, rules, checklists, database, voice pipeline, and AI calls—runs on the other machine. This is the better option if you want MARA’s game-PC footprint to stay small, at the cost of a little more setup and dependence on the network connection.

> **Which one should I use?**
> Start with all-in-one. Switch to a split install if you are short on RAM, want to keep background CPU work away from DCS, or already have a machine that can host the backend.

## Start here

The early-access client is a Windows application. Your access package includes the combined installer, the standalone backend package for split installations, and the service details you need.

1. In Windows, set the microphone and audio output you want as the default devices.
2. Close DCS, then run `MARA-Setup-<version>.exe`.
3. Leave **Install or update DCS-BIOS and MARA spatial export** enabled. Setup detects supported DCS Saved Games folders and downloads the pinned DCS-BIOS release.
4. Launch MARA. For the normal all-in-one setup, leave **Backend mode** set to **Local**. No MARA account is required.
5. Open **Settings**, enter your OpenAI API key in **OpenAI API key (local only)**, and choose **Save settings**.
6. Keep MARA open while the local backend downloads the Kokoro voice files. Wait for **Local backend**, **Kokoro voice**, and **OpenAI API** to show ready states.
7. Bind push-to-talk and MARA mute to different function keys or HOTAS buttons.
8. Return to **Overview** and choose **Start MARA**.
9. Start or restart DCS, load into the F/A-18C, and wait for cockpit data to appear.

If setup does not find DCS, open MARA Settings and select the Saved Games folder yourself. Select the profile folder—such as `C:\Users\you\Saved Games\DCS`—not the main DCS installation directory.

### What the DCS setup changes

MARA installs the pinned DCS-BIOS release under your selected Saved Games folder, adds its spatial export and in-game text hook, and adds the required lines to `Scripts\Export.lua`. Existing export lines from tools such as Tacview are preserved. Before replacing DCS-BIOS or changing an existing file, MARA creates a timestamped backup beside it.

The install/repair action is repeatable. Restart DCS after running it so DCS reloads the integration. Uninstalling the desktop application does not remove DCS-BIOS, the added export files, their backups, or locally stored MARA data.

## Your first sortie

Use a simple cold-start or free-flight mission for the first run.

### 1. Check the status panel

Before entering the cockpit, confirm that **DCS-BIOS** and **Backend** show ready and that **MARA** is running. In Settings, local mode also shows separate status cards for the backend process, Kokoro voice files, and OpenAI API access.

Make one test push-to-talk call before the sortie. The microphone is opened only while you hold PTT, so this is also the practical check that the Windows default input and output devices are correct.

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

Close DCS, open the desktop app, and use **Install / repair DCS-BIOS**. Confirm that the selected Saved Games folder matches the DCS variant you actually launched, then restart DCS.

### DCS-BIOS installation fails

The setup action downloads a pinned DCS-BIOS archive from GitHub and rejects it if the checksum or archive layout is wrong. Check the internet connection, then retry from MARA. If the error persists, include the exact error in the report but do not attach credentials.

### The local backend stays on “Downloading”

The first local start downloads and verifies roughly 340 MB of Kokoro voice data. Keep MARA open and allow the download to finish. Partial downloads are resumed automatically. Open **Settings → Open logs** if the progress stops or the backend exits.

### OpenAI API says “API key needed”, “Invalid key”, or “Quota/rate limited”

Enter the key in the local-only field and save the settings. Replace a rejected key in the same field. A quota or rate-limit message means the key was accepted but its OpenAI project cannot currently serve requests. “Offline” means the backend could not reach the OpenAI API.

### MARA uses the wrong microphone or speakers

Change the default input and output devices in Windows, then restart MARA. The current desktop interface does not yet expose separate device selectors.

### My HOTAS button is not detected

Reconnect the controller, reopen Settings, choose **Refresh**, and use **Detect button** again. The current Windows build supports buttons 1–32 on devices exposed by the Windows joystick API. You can use an F1–F24 keyboard key instead.

### MARA hears me but does not answer

Check the backend, Kokoro, and OpenAI status cards, then verify that assistant mute is off and that the correct output is the Windows default device. A short tone confirms when mute changes.

### A remote backend will not connect

Use **Test connection** in Settings. Confirm the URL, firewall rule, and backend status. A private LAN may use an unencrypted local connection; a public backend requires HTTPS/WSS. An incompatible backend API must be updated to match the desktop client.

### Coach mode says unavailable

The current mission or multiplayer server may deny the required DCS export data. That is a capability restriction, not necessarily a connection failure.

## Early-access expectations

The first release is focused on Windows and the F/A-18C. Aircraft coverage, live multiplayer behaviour, and installer compatibility are being expanded through explicit validation—not assumed from simulator fixtures. MARA is planned to be released as open source.

When you report a problem, include the aircraft, mission type, DCS version, what the status panel showed, and the exact steps immediately before the issue. Do not include credentials or private tokens.
