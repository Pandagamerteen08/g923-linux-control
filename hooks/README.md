# Telemetry hooks

Drop a `.json` or `.py` file in this directory (or in
`~/.config/g923-linux-control/hooks/`) and it appears in
**Rev LEDs & Telemetry Hooks → Telemetry feed** after **Rescan hooks**.

Hooks are trusted local code. The application does not sandbox Python hooks;
only install files you wrote or reviewed.

## Data contract

Each poll returns one object with at least one of `rpm` or `throttle`.
Everything else is optional:

| Field        | Type   | Notes                                            |
| ------------ | ------ | ------------------------------------------------ |
| `rpm`        | number | Engine speed                                     |
| `max_rpm`    | number | Redline; defaults to the value in settings       |
| `throttle`   | 0–1 or 0–100 | Pedal travel                               |
| `brake`      | 0–1 or 0–100 | Optional status readout                    |
| `clutch`     | 0–1 or 0–100 | Optional status readout                    |
| `gear`       | int    | Optional status readout                          |
| `speed_kmh`  | number | Optional status readout                          |

`max_rpm` is required for a usable ratio unless the settings fallback value is
appropriate. If a feed stops updating for `telemetry.stale_timeout_ms`
(800 ms by default), the pedal fallback takes over automatically.

## JSON hook

```json
{
  "schema": "g923-linux-control/hook@1",
  "name": "My game bridge",
  "description": "Reads a telemetry file written by a bridge.",
  "poll_interval_ms": 100,
  "source": {
    "type": "file",
    "path": "~/.local/share/my-game/telemetry.json"
  },
  "fields": {
    "rpm": "engineRpm",
    "max_rpm": "maxRpm",
    "throttle": "throttle"
  }
}
```

`source.type` can be `file` or `command`.

For a command, provide an argv list (no shell) that prints one JSON object to
stdout:

```json
"source": {
  "type": "command",
  "command": ["python3", "~/bin/my-telemetry-dump.py"]
}
```

Supported optional keys: `schema` (informational), `name`, `description`,
`poll_interval_ms` (16–1000), `fields` (map logical name → payload key).

Well-known key aliases are detected automatically (`engineRpm`, `RPM`,
`maxRpm`, `redline`, `throttle`, `ThrottleInput`, `Speed`, …), so `fields` is
only needed for unusual payloads.

## Python hook

```python
"""Minimal polling hook."""
from pathlib import Path
import json

HOOK_NAME = "My game bridge"
HOOK_DESCRIPTION = "Reads telemetry from a JSON file."
HOOK_INTERVAL_MS = 100

TELEMETRY_FILE = Path("~/.local/share/my-game/telemetry.json")


def poll() -> dict | None:
    try:
        return json.loads(TELEMETRY_FILE.expanduser().read_text())
    except (OSError, json.JSONDecodeError):
        return None
```

* `poll()` runs in a background thread at the configured interval.
* Return `None` while waiting for the game; the UI shows the error instead of
  crashing.
* Keep `poll()` fast (well under the interval). There is no way to cancel a
  blocking call inside user code.
* Async hooks are rejected; use a synchronous function.
* Importing the hook happens once, in the polling thread.

## Files in this directory

* `snowrunner_file_bridge.json` — reads a JSON file written by a SnowRunner
  telemetry bridge. Enable the bridge in the game/Proton prefix and adjust the
  path if your bridge writes elsewhere.
* `example_telemetry_hook.py` — a commented Python template you can copy and
  adapt.

## Security and privacy

Hooks run locally with your user's permissions. The application never uploads
telemetry, never opens a network listener, and never starts a background
service. A JSON hook can run a local command if you write one; that is your
choice, not the application's.
