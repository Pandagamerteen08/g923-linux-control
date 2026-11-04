"""Telemetry package: game hooks, LED rendering and the pedal fallback.

Public names are resolved lazily so the pure rendering/fallback modules can be
imported in environments without PyQt6 (for example headless unit checks).
"""

from __future__ import annotations

import importlib

__all__ = [
    "HookCatalog",
    "HookPoller",
    "HookSpec",
    "LedController",
    "LedEngine",
    "LedFrame",
    "PedalFallback",
    "TelemetrySample",
    "discover_hooks",
]

_MODULE_BY_NAME = {
    "HookCatalog": ".hooks",
    "HookPoller": ".hooks",
    "HookSpec": ".hooks",
    "TelemetrySample": ".hooks",
    "discover_hooks": ".hooks",
    "LedEngine": ".led_engine",
    "LedFrame": ".led_engine",
    "PedalFallback": ".fallback",
    "LedController": ".led_controller",
}


def __getattr__(name: str):
    module_name = _MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    return getattr(module, name)
