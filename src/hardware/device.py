"""Discovery of the wheel across evdev, hidraw and sysfs.

The G923 exposes several USB product IDs depending on its mode switch.  This
module finds the corresponding input node, the kernel HID device directory and
the matching ``hidraw`` node, then reads whatever firmware information the
kernel makes available.

Nothing here requires root; unreadable device nodes are reported as warnings so
the UI can explain the udev rule needed to fix them.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..constants import SUPPORTED_PRODUCTS, VENDOR_ID

log = logging.getLogger(__name__)

try:  # pragma: no cover - exercised implicitly by import
    import evdev
    from evdev import InputDevice, list_devices

    EVDEV_AVAILABLE = True
except ImportError:  # pragma: no cover - optional at import time
    evdev = None  # type: ignore[assignment]
    InputDevice = None  # type: ignore[assignment]
    list_devices = None  # type: ignore[assignment]
    EVDEV_AVAILABLE = False

#: User-facing remediation for permission errors.
PERMISSION_HINT = (
    "Grant device access with a udev rule, for example "
    '/etc/udev/rules.d/70-g923-linux-control.rules containing: '
    'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", '
    'MODE="0660", GROUP="input" — then run '
    "`sudo udevadm control --reload-rules && sudo udevadm trigger` "
    "and reconnect the wheel."
)

_HID_DIR_PATTERN = re.compile(r"^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}\.\w+$")
_HIDRAW_ROOT = Path("/sys/class/hidraw")
_HID_DEVICES_ROOT = Path("/sys/bus/hid/devices")


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """A detected wheel and the kernel nodes that belong to it."""

    event_path: str
    name: str
    vendor_id: int
    product_id: int
    phys: str = ""
    uniq: str = ""
    hidraw_path: str = ""
    hid_dir: str = ""
    driver_name: str = ""
    firmware: str = ""
    usb_release: str = ""

    @property
    def id_string(self) -> str:
        """``046d:c267`` style identifier used in status messages."""
        return f"{self.vendor_id:04x}:{self.product_id:04x}"

    @property
    def mode_label(self) -> str:
        """USB mode description for the detected product ID."""
        return SUPPORTED_PRODUCTS.get(self.product_id, "G923 · unknown USB mode")

    @property
    def firmware_display(self) -> str:
        """Human-readable firmware/USB release string for the header."""
        if self.firmware and self.usb_release:
            return f"{self.firmware} · USB {self.usb_release}"
        if self.firmware:
            return self.firmware
        if self.usb_release:
            return f"USB release {self.usb_release}"
        return "Not reported by kernel"


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Result of a discovery pass, including recoverable problems."""

    devices: tuple[DeviceInfo, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def primary(self) -> DeviceInfo | None:
        """The best candidate, or ``None`` when nothing was found."""
        return self.devices[0] if self.devices else None


# ---------------------------------------------------------------------------
# sysfs helpers
# ---------------------------------------------------------------------------
def _parse_hid_id(text: str) -> tuple[int, int] | None:
    """Parse ``HID_ID=0003:0000046D:0000C267`` into ``(vendor, product)``."""
    for line in text.splitlines():
        if line.startswith("HID_ID="):
            parts = line.split("=", 1)[1].strip().split(":")
            if len(parts) != 3:
                return None
            try:
                return int(parts[1], 16), int(parts[2], 16)
            except ValueError:
                return None
    return None


@lru_cache(maxsize=16)
def _hid_dirs_for(product_id: int) -> tuple[Path, ...]:
    """Return every HID sysfs directory matching ``vendor:product``."""
    matches: list[Path] = []
    if not _HID_DEVICES_ROOT.is_dir():
        return ()
    try:
        entries = list(_HID_DEVICES_ROOT.iterdir())
    except OSError:
        return ()
    for entry in entries:
        uevent = entry / "uevent"
        try:
            ids = _parse_hid_id(uevent.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if ids == (VENDOR_ID, product_id):
            matches.append(entry)
    return tuple(matches)


def _driver_name(hid_dir: Path) -> str:
    """Resolve the name of the kernel driver bound to ``hid_dir``."""
    driver_link = hid_dir / "driver"
    try:
        return driver_link.resolve().name
    except OSError:
        return ""


def _usb_release(product_id: int) -> str:
    """Read ``bcdDevice`` from the USB device, formatted as ``1.02``."""
    root = Path("/sys/bus/usb/devices")
    if not root.is_dir():
        return ""
    try:
        entries = list(root.iterdir())
    except OSError:
        return ""
    for entry in entries:
        try:
            vendor = (entry / "idVendor").read_text(encoding="utf-8").strip()
            product = (entry / "idProduct").read_text(encoding="utf-8").strip()
            if vendor.lower() != f"{VENDOR_ID:04x}" or product.lower() != f"{product_id:04x}":
                continue
            raw = (entry / "bcdDevice").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        try:
            value = int(raw, 16)
        except ValueError:
            return raw
        return f"{(value >> 8) & 0xFF}.{value & 0xFF:02d}"
    return ""


@lru_cache(maxsize=16)
def _firmware_for(product_id: int) -> str:
    """Best-effort firmware string, if a driver exposes one in sysfs."""
    for hid_dir in _hid_dirs_for(product_id):
        for attribute in ("firmware_version", "fw_version", "firmware_revision"):
            candidate = hid_dir / attribute
            try:
                if candidate.is_file():
                    value = candidate.read_text(encoding="utf-8").strip()
                    if value:
                        return value
            except OSError:
                continue
    return ""


@lru_cache(maxsize=16)
def find_hidraw(product_id: int) -> str:
    """Locate ``/dev/hidrawN`` for the wheel, used for LED output reports."""
    if not _HIDRAW_ROOT.is_dir():
        return ""
    try:
        entries = list(_HIDRAW_ROOT.iterdir())
    except OSError:
        return ""
    for entry in entries:
        uevent = entry / "device" / "uevent"
        try:
            ids = _parse_hid_id(uevent.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if ids == (VENDOR_ID, product_id):
            node = Path("/dev") / entry.name
            if node.exists():
                return str(node)
    return ""


def _hid_dir_for_input(sys_input: Path) -> Path | None:
    """Walk up from an input node to the enclosing HID device directory."""
    try:
        current = sys_input.resolve()
    except OSError:
        return None
    for parent in (current, *current.parents):
        if _HID_DIR_PATTERN.match(parent.name) and (parent / "uevent").exists():
            return parent
    return None


# ---------------------------------------------------------------------------
# evdev discovery
# ---------------------------------------------------------------------------
def _capabilities_score(device: "InputDevice") -> int:
    """Rank input nodes so the wheel is preferred over auxiliary interfaces."""
    try:
        caps = device.capabilities(absinfo=False)
    except OSError:
        return 0
    score = 0
    axes = set(caps.get(evdev.ecodes.EV_ABS, []))
    keys = set(caps.get(evdev.ecodes.EV_KEY, []))
    if evdev.ecodes.ABS_X in axes:
        score += 5
    if evdev.ecodes.ABS_HAT0X in axes or evdev.ecodes.ABS_HAT0Y in axes:
        score += 2
    score += len(axes & {evdev.ecodes.ABS_Y, evdev.ecodes.ABS_Z, evdev.ecodes.ABS_RZ})
    if 0x13C in keys:  # BTN_MODE: the wheel's centre button
        score += 3
    return score


def discover_devices(product_filter: int | None = None) -> DiscoveryReport:
    """Scan evdev for supported wheels.

    Args:
        product_filter: When set, only report this USB product ID.

    Returns:
        A :class:`DiscoveryReport` with candidates ranked best-first.  The
        report never raises; import and permission problems are surfaced as
        warnings so the application can keep running headless of hardware.
    """
    if not EVDEV_AVAILABLE:
        return DiscoveryReport(
            warnings=(
                "The python-evdev package is not installed. "
                "Install it with `pip install -r requirements.txt`.",
            )
        )

    warnings: list[str] = []
    raw_devices: list[tuple[int, DeviceInfo]] = []

    try:
        paths = list_devices()
    except (PermissionError, OSError) as exc:
        log.warning("Could not enumerate input devices: %s", exc)
        return DiscoveryReport(warnings=(f"Could not enumerate input devices: {exc}",))

    for path in paths:
        device = None
        try:
            device = InputDevice(path)
            info = device.info
            if info.vendor != VENDOR_ID:
                continue
            name = device.name or ""
            if info.product not in SUPPORTED_PRODUCTS and "G923" not in name:
                continue
            if product_filter is not None and info.product != product_filter:
                continue
            score = _capabilities_score(device)
            if score < 5:
                # Vendor 046d also makes keyboards and mice; require at least a
                # steering axis before treating the node as the wheel.
                continue

            sys_input = Path("/sys/class/input") / Path(path).name / "device"
            hid_dir = _hid_dir_for_input(sys_input)
            record = DeviceInfo(
                event_path=path,
                name=name,
                vendor_id=info.vendor,
                product_id=info.product,
                phys=device.phys or "",
                uniq=device.uniq or "",
                hidraw_path=find_hidraw(info.product),
                hid_dir=str(hid_dir) if hid_dir else "",
                driver_name=_driver_name(hid_dir) if hid_dir else "",
                firmware=_firmware_for(info.product),
                usb_release=_usb_release(info.product),
            )
            raw_devices.append((score, record))
        except PermissionError:
            warnings.append(f"Permission denied opening {path}. {PERMISSION_HINT}")
        except OSError as exc:
            log.debug("Skipping %s: %s", path, exc)
        finally:
            if device is not None:
                try:
                    device.close()
                except OSError:
                    pass

    raw_devices.sort(key=lambda item: item[0], reverse=True)
    return DiscoveryReport(
        devices=tuple(record for _, record in raw_devices),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def event_path_is_alive(path: str) -> bool:
    """Cheap liveness check for the currently opened input node."""
    return bool(path) and Path(path).exists()
