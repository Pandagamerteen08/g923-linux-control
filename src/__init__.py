"""G923 Linux Control — an offline desktop control panel for a racing wheel.

The package is intentionally split into three layers:

* :mod:`src.hardware` — evdev input decoding and kernel driver control.
* :mod:`src.telemetry` — game hooks, LED rendering and the pedal fallback.
* :mod:`src.gui` — PyQt6 presentation layer, widgets and styling.

No module in this package performs network I/O or starts a background daemon.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
