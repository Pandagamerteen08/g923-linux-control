"""Hardware integration layer.

Everything here talks to the Linux kernel through documented interfaces:

* ``evdev`` character devices for input events,
* ``sysfs`` attributes exposed by ``hid-lg4ff`` / ``hid-logitech-hidpp``,
* ``hidraw`` for the rev-LED output report.

The layer never runs as root and never installs udev rules or modules; when a
write is refused the user gets an actionable message describing the missing
permission or driver feature.

Names are imported lazily so the driver/probe modules can be used (and tested)
without PyQt6 or an input device present.
"""

from __future__ import annotations

import importlib

__all__ = [
    "DeviceInfo",
    "DiscoveryReport",
    "DriverSnapshot",
    "EvdevReader",
    "SysfsDriver",
    "discover_devices",
]

_MODULE_BY_NAME = {
    "DeviceInfo": ".device",
    "DiscoveryReport": ".device",
    "discover_devices": ".device",
    "EvdevReader": ".evdev_reader",
    "DriverSnapshot": ".sysfs",
    "SysfsDriver": ".sysfs",
}


def __getattr__(name: str):
    module_name = _MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    return getattr(module, name)
