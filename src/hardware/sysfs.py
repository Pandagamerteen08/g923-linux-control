"""Force-feedback and rotation control through kernel sysfs attributes.

The in-tree ``hid-lg4ff`` driver and the out-of-tree new-lg4ff module expose
writable attributes under ``/sys/bus/hid/drivers/logitech/<device>/``::

    range         270..900   steering lock in degrees
    gain          0..65535   global force-feedback gain
    autocenter    0..65535   centring spring strength
    spring_level  0..100     spring effect gain
    damper_level  0..100     damper effect gain

HID++ wheels expose a ``range`` attribute through ``hid-logitech-hidpp`` as
well.  Everything is probed at runtime: unsupported knobs are reported rather
than guessed at, and permission failures carry the udev hint the user needs.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import SteeringSettings
from ..constants import SYSFS_ATTRIBUTES, VENDOR_ID
from .device import PERMISSION_HINT

log = logging.getLogger(__name__)

_HID_ID_RE = re.compile(
    r"^HID_ID=0003:([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8})$", re.MULTILINE
)
_INT_RE = re.compile(r"-?\d+")
_HID_DEVICES_ROOT = Path("/sys/bus/hid/devices")
_HID_DRIVERS_ROOT = Path("/sys/bus/hid/drivers")

#: Alternate attribute spellings seen across driver versions.
_ALIASES: dict[str, tuple[str, ...]] = {
    "range": ("range",),
    "gain": ("gain", "ffb_gain"),
    "autocenter": ("autocenter", "spring"),
    "spring_level": ("spring_level", "spring"),
    "damper_level": ("damper_level", "damper"),
    "friction_level": ("friction_level", "friction"),
}


class DriverError(RuntimeError):
    """Raised when a sysfs attribute cannot be written."""


class DriverPermissionError(DriverError):
    """Raised when the kernel refuses a write because of permissions."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"Permission denied writing {path}. {PERMISSION_HINT}"
        )
        self.path = path


@dataclass(frozen=True, slots=True)
class ApplyReport:
    """Outcome of applying a :class:`SteeringSettings` bundle."""

    applied: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    control_dir: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.applied) and not self.errors

    @property
    def summary(self) -> str:
        if not self.control_dir:
            return "No writable kernel control node found."
        parts: list[str] = []
        if self.applied:
            parts.append("Applied " + ", ".join(self.applied))
        if self.unsupported:
            parts.append("Not supported: " + ", ".join(self.unsupported))
        if self.errors:
            parts.append("; ".join(self.errors))
        return " · ".join(parts) or "Nothing to apply."


@dataclass(frozen=True, slots=True)
class DriverSnapshot:
    """Current, read-only view of the driver binding for the UI."""

    available: bool = False
    control_dir: str = ""
    driver_name: str = ""
    attributes: tuple[str, ...] = ()
    values: dict[str, int] = field(default_factory=dict)
    writable: bool = False

    @property
    def status_text(self) -> str:
        if not self.available:
            return "No kernel control attributes found"
        driver = self.driver_name or "unknown driver"
        return f"{driver} · {len(self.attributes)} attribute(s)"


def _read_hid_ids(directory: Path) -> tuple[int, int] | None:
    """Read vendor/product IDs from a HID device's ``uevent`` file."""
    try:
        text = (directory / "uevent").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _HID_ID_RE.search(text)
    if not match:
        return None
    return int(match.group(1), 16), int(match.group(2), 16)


def _first_int(text: str) -> int | None:
    """Extract the effective value from a sysfs attribute's text."""
    numbers = _INT_RE.findall(text)
    if not numbers:
        return None
    try:
        # ``range`` historically reported "min max current"; every other
        # attribute is a single integer.
        return int(numbers[-1])
    except ValueError:
        return None


class SysfsDriver:
    """Write force-feedback settings straight to the kernel driver."""

    def __init__(self, vendor_id: int = VENDOR_ID, product_id: int | None = None) -> None:
        self._vendor_id = vendor_id
        self._product_id = product_id
        self._control_dir: Path | None = None
        self._probed = False

    # -- discovery --------------------------------------------------------
    def _score(self, directory: Path) -> int:
        """Rank candidate device directories by useful attributes."""
        score = 0
        for name in SYSFS_ATTRIBUTES:
            for alias in _ALIASES.get(name, (name,)):
                candidate = directory / alias
                if candidate.exists():
                    score += 2
                    if os.access(candidate, os.W_OK):
                        score += 1
                    break
        driver_link = directory / "driver"
        try:
            driver_name = driver_link.resolve().name
        except OSError:
            driver_name = ""
        if driver_name and driver_name != "hid-generic":
            score += 1
        return score

    def _discover(self) -> Path | None:
        """Find the best HID sysfs directory for the configured wheel."""
        candidates: dict[Path, int] = {}

        roots = [_HID_DEVICES_ROOT]
        if _HID_DRIVERS_ROOT.is_dir():
            try:
                roots.extend(
                    entry for entry in _HID_DRIVERS_ROOT.iterdir() if entry.is_dir()
                )
            except OSError:
                pass

        for root in roots:
            try:
                entries = list(root.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    resolved = entry.resolve()
                except OSError:
                    continue
                if not resolved.is_dir() or resolved in candidates:
                    continue
                ids = _read_hid_ids(resolved)
                if ids is None or ids[0] != self._vendor_id:
                    continue
                if self._product_id is not None and ids[1] != self._product_id:
                    continue
                score = self._score(resolved)
                if score:
                    candidates[resolved] = score

        if not candidates:
            return None
        return max(candidates, key=lambda path: candidates[path])

    def _ensure_dir(self) -> Path | None:
        if not self._probed:
            self._control_dir = self._discover()
            self._probed = True
        return self._control_dir

    def invalidate(self) -> None:
        """Force a fresh probe, e.g. after the wheel was reconnected."""
        self._control_dir = None
        self._probed = False

    def snapshot(self, refresh: bool = False) -> DriverSnapshot:
        """Return the driver's current attributes and values."""
        if refresh:
            self.invalidate()
        directory = self._ensure_dir()
        if directory is None:
            return DriverSnapshot()

        attributes: list[str] = []
        values: dict[str, int] = {}
        writable = False
        for name, aliases in _ALIASES.items():
            for alias in aliases:
                attribute = directory / alias
                if not attribute.exists():
                    continue
                attributes.append(alias)
                try:
                    parsed = _first_int(attribute.read_text(encoding="utf-8"))
                except OSError:
                    parsed = None
                if parsed is not None:
                    values[alias] = parsed
                if os.access(attribute, os.W_OK):
                    writable = True
                break

        try:
            driver_name = (directory / "driver").resolve().name
        except OSError:
            driver_name = ""

        return DriverSnapshot(
            available=bool(attributes),
            control_dir=str(directory),
            driver_name=driver_name,
            attributes=tuple(attributes),
            values=values,
            writable=writable,
        )

    # -- writing ----------------------------------------------------------
    def _attribute_path(self, logical: str) -> Path | None:
        """Resolve the first existing alias for a logical attribute name."""
        directory = self._ensure_dir()
        if directory is None:
            return None
        for alias in _ALIASES.get(logical, (logical,)):
            path = directory / alias
            if path.exists():
                return path
        return None

    @staticmethod
    def _write(path: Path, value: int) -> None:
        try:
            path.write_text(f"{int(value)}\n", encoding="ascii")
        except PermissionError as exc:
            raise DriverPermissionError(path) from exc
        except OSError as exc:
            raise DriverError(f"Could not write {path.name}: {exc}") from exc

    def apply(self, steering: SteeringSettings) -> ApplyReport:
        """Apply rotation, gain, damper and spring settings.

        Missing attributes are reported in ``unsupported`` instead of raising,
        so a partially featured driver still receives the settings it supports.
        """
        steering = steering.normalized()
        directory = self._ensure_dir()
        if directory is None:
            return ApplyReport(
                unsupported=("range", "gain", "damper_level", "spring_level")
            )

        applied: list[str] = []
        unsupported: list[str] = []
        errors: list[str] = []

        def push(
            logical: str,
            display: str,
            value: int,
            raw_range: tuple[int, int] = (0, 0),
        ) -> None:
            path = self._attribute_path(logical)
            if path is None:
                unsupported.append(display)
                return
            if raw_range != (0, 0):
                low, high = raw_range
                value = max(low, min(high, int(value)))
            try:
                self._write(path, value)
            except DriverError as exc:
                errors.append(str(exc))
            else:
                applied.append(display)

        # Rotation first: it is the setting games notice immediately.
        push("range", "range", steering.rotation_deg)

        gain_path = self._attribute_path("gain")
        if gain_path is not None:
            push("gain", "gain", round(steering.ffb_gain * 65535 / 100), (0, 65535))
        else:
            unsupported.append("gain")

        if self._attribute_path("damper_level") is not None:
            push("damper_level", "damper", steering.damper, (0, 100))
        else:
            unsupported.append("damper")

        spring_path = self._attribute_path("spring_level")
        if spring_path is not None:
            push("spring_level", "spring", steering.spring, (0, 100))
        elif self._attribute_path("autocenter") is not None:
            push("autocenter", "spring", round(steering.spring * 65535 / 100), (0, 65535))
        else:
            unsupported.append("spring")

        if errors:
            log.warning("Driver writes failed: %s", "; ".join(errors))
        return ApplyReport(
            applied=tuple(applied),
            unsupported=tuple(unsupported),
            errors=tuple(errors),
            control_dir=str(directory),
        )
