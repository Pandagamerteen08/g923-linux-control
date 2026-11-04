"""Example Python telemetry hook.

Copy this file, point ``TELEMETRY_FILE`` at whatever your game bridge writes,
and adapt the parsing.  A hook returns a mapping from :func:`poll`; the
application normalizes it and drives the rev LEDs.

The feeder only needs to write a JSON object such as::

    {"engineRpm": 5420, "maxRpm": 7000, "throttle": 0.83}

Run with ``python -u`` from the bridge so the file is updated continuously.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOOK_NAME = "Example JSON-file hook"
HOOK_DESCRIPTION = "Template that reads a single JSON telemetry document."
HOOK_INTERVAL_MS = 100

TELEMETRY_FILE = Path("~/.local/share/g923-linux-control/telemetry.json")


def poll() -> dict[str, Any] | None:
    """Return the latest telemetry object, or ``None`` while waiting.

    ``None`` is treated as "source not ready": the UI shows a waiting message
    and the pedal fallback takes over after the stale timeout.
    """
    try:
        payload = json.loads(TELEMETRY_FILE.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload
