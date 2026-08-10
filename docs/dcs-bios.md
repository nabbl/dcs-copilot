# DCS-BIOS connection and diagnostics

## Installation boundary

DCS Copilot does not install or modify DCS-BIOS. Install the standard
DCS-Skunkworks release under the DCS Saved Games tree and configure its normal
`Export.lua` entry according to the upstream instructions. This application
opens only the read-only export multicast socket; it does not open the DCS-BIOS
command/import port.

Set `DCS_BIOS_PATH` to either of these locations:

```text
C:\Users\<you>\Saved Games\DCS\Scripts\DCS-BIOS
C:\Users\<you>\Saved Games\DCS\Scripts\DCS-BIOS\doc\json
```

`DCS.openbeta` and Saved Games inside OneDrive are auto-discovery candidates as
well. The generated JSON directory must contain module files such as
`MetadataStart.json` and `FA-18C_hornet.json`. When metadata is missing, status
reports it rather than falling back to hardcoded addresses.

## Network defaults

```text
Group:     239.255.50.10
Port:      5010/UDP
Interface: 127.0.0.1
```

The receiver binds the UDP port with `SO_REUSEADDR`, joins the multicast group
on loopback, and keeps the socket non-blocking. Override the group, port, or
interface only when the DCS-BIOS `BIOSConfig.lua` export settings were changed.

## Commands

Run a bounded health check:

```bash
uv run dcs-copilot status --wait 2
```

Watch decoded symbolic controls:

```bash
uv run dcs-copilot watch
uv run dcs-copilot watch --raw --module FA-18C_hornet
uv run dcs-copilot watch --raw --module FA-18C_hornet --control MASTER_CAUTION_LT
```

Normal `watch` output contains normalized field changes and availability status.
`--raw` compares decoded controls and prints changes only. Neither mode prints
every 30 Hz packet. A control is decoded only after every byte required by its
metadata has been exported.

## Failure behavior

- No frames within the stale timeout marks the client disconnected and clears
  all state availability, preventing old cockpit values from being reused.
- A malformed write header increments the parser error counter and suspends
  parsing until the next valid sync marker.
- A truncated write is never partially applied.
- Bad JSON files are skipped and reported as degraded registry health.
- `_ACFT_NAME` values `NONE`, empty, or unavailable produce no detected aircraft.
- CommonData IAS/altitude/heading remain unavailable until its model-time counter
  advances, which distinguishes a live ownship export from cached/default bytes.

If status reports frames but no aircraft, verify that `MetadataStart.json` is
present and use the DCS-BIOS control reference to confirm `_ACFT_NAME` updates.
If it reports no frames, first verify DCS-BIOS itself with its control-reference
tool, then check that DCS-BIOS and DCS Copilot use the same multicast group, port,
and network interface.
