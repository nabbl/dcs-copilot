# Windows client and installer

## Customer flow

`DCS-Copilot-Setup-<version>.exe` installs two bundled applications without
requiring Python:

- **DCS Copilot** is the normal windowed client;
- **dcs-copilot** is the diagnostics and DCS setup command-line helper.

The installer offers to install/repair DCS-BIOS in every detected `DCS`,
`DCS.openbeta`, or `DCS.openalpha` Saved Games directory. If DCS has not yet
created one, the customer selects it later in the app. Setup downloads the
pinned upstream ZIP over HTTPS, verifies the release SHA-256, and rejects
unexpected or unsafe archive layouts. Existing DCS-BIOS and `Export.lua` files
receive timestamped sibling backups. Uninstalling DCS Copilot deliberately does
not delete DCS-BIOS, `Export.lua`, their backups, or account data in the cloud.

The first app screen signs in or creates an account. The main screen then shows
account, DCS-BIOS, and runtime state; settings expose the Saved Games path,
service URL, F13–F24 push-to-talk key, speech mode, and optional Windows login
launch. The activity view contains local runtime output. It must not display
tokens, passwords, raw audio, or cockpit snapshots.

## Build an installer

On a Windows x64 build host, install `uv` and Inno Setup 6, then run:

```powershell
./packaging/windows/build.ps1 -Version 0.1.0 `
  -ServiceUrl "wss://api.example.com/v1/realtime"
```

The script synchronizes the workspace, builds separate PyInstaller windowed and
console bundles, then invokes Inno Setup. Output is written below
`dist/windows/`. The GitHub Actions workflow performs the same build and uploads
the installer artifact. Configure its `DCS_COPILOT_SERVICE_URL` repository
variable for release builds; a production client URL must use `wss://`.

Qt Essentials is intentionally used instead of the full Qt distribution. The
desktop bundle still has a larger footprint than the previous CLI, but avoids
shipping Qt WebEngine, multimedia, and other unused add-ons.

## Release gates

The generated development installer is unsigned. A customer release should not
be published until the pipeline signs both application executables and the
final installer with the company code-signing certificate and applies a trusted
timestamp. Otherwise Windows SmartScreen may warn customers and executable
identity cannot be verified.

Before release, test on clean Windows 10 and 11 VMs with:

- default and relocated Saved Games folders;
- DCS and DCS.openbeta side by side;
- no existing `Export.lua`, an existing multi-plugin file, and an existing
  DCS-BIOS installation;
- successful login, invalid credentials, expired access, refresh rotation,
  logout, backend outage, and reconnect after 15 minutes;
- microphone/output device changes, F13–F24 capture, DCS focus loss, repair,
  upgrade, and uninstall.

Production backend gates still include PostgreSQL migrations, TLS termination,
per-account/IP authentication rate limits, password reset/email verification,
device/session management, entitlement enforcement, monitoring, and secret
rotation. The current backend authentication protocol is functional, but those
operational controls are required before a paid public launch.
