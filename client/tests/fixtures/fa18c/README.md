# F/A-18C indication replay fixtures

Do not add invented radar, RWR, or SA payloads here. Fixtures must be minimized
from versioned live recordings produced by `mara indications record` and must
retain the raw indication string that supports the asserted transition.

Planned layout after discovery:

```text
radar/no-contact.jsonl
radar/contact.jsonl
radar/lock.jsonl
radar/lock-lost.jsonl
rwr/search.jsonl
rwr/lock.jsonl
rwr/launch.jsonl
sa/empty.jsonl
sa/multiple-tracks.jsonl
```

Each committed fixture needs a companion metadata file or header documenting
DCS version, DCS-BIOS version, aircraft, indicator IDs, page visibility, test
action, and sanitization performed. A missing field remains unavailable; tests
must not turn absence into `false`.

Before copying a local recording into this tree, run:

```bash
mara indications validate diagnostics/indication-recordings/<scenario>
mara indications replay diagnostics/indication-recordings/<scenario> --diff
```
