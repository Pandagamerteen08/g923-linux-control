"""Application-wide constants shared by the hardware, telemetry and GUI layers.

The values here describe the physical wheel only.  They intentionally contain
no vendor-branded product names beyond the model the utility targets, and no
user configuration (that lives in :mod:`src.config`).
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
APP_NAME = "G923 Linux Control"
APP_ID = "g923-linux-control"
APP_VERSION = "1.0.0"
APP_SUMMARY = (
    "Offline Linux control panel for the Logitech G923 racing wheel: "
    "force feedback, pedal diagnostics and rev LEDs."
)
PROJECT_URL = "https://github.com/Pandagamerteen08/g923-linux-control"

# ---------------------------------------------------------------------------
# USB / HID identification
# ---------------------------------------------------------------------------
VENDOR_ID = 0x046D

#: Product IDs reported by the wheel in its different USB modes.  The value is
#: a human readable mode label, not a vendor product name.
SUPPORTED_PRODUCTS: dict[int, str] = {
    0xC266: "G923 · PlayStation / PC mode",
    0xC267: "G923 · PlayStation / PC mode",
    0xC26D: "G923 · Xbox / PC mode",
    0xC26E: "G923 · Xbox / PC mode",
}

#: Kernel HID drivers that can own the wheel.  ``logitech`` is the in-tree
#: ``hid-lg4ff`` driver (also the name used by the new-lg4ff DKMS module);
#: ``logitech-hidpp-device`` is the HID++ driver used by the Xbox variant.
HID_DRIVER_NAMES = ("logitech", "logitech-hidpp-device", "hid-generic")

#: sysfs attributes exposed by hid-lg4ff / new-lg4ff.  Each entry maps the
#: attribute name to the inclusive range accepted when writing to it.
SYSFS_ATTRIBUTES: dict[str, tuple[int, int]] = {
    "range": (270, 900),
    "gain": (0, 65535),
    "autocenter": (0, 65535),
    "spring_level": (0, 100),
    "damper_level": (0, 100),
    "friction_level": (0, 100),
    "combine_pedals": (0, 2),
}

#: Directories scanned for a writable wheel control node, in priority order.
SYSFS_DRIVER_ROOTS = (
    Path("/sys/bus/hid/drivers"),
    Path("/sys/bus/hid/devices"),
)

# ---------------------------------------------------------------------------
# evdev axis mapping (Linux input event codes)
# ---------------------------------------------------------------------------
ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02
ABS_RZ = 0x05
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11

#: Logical name for each analogue channel.  Pedal polarity is auto-calibrated
#: at runtime, so these assignments only need to be channel-correct.
AXIS_MAP: dict[int, str] = {
    ABS_X: "steering",
    ABS_Y: "throttle",
    ABS_Z: "brake",
    ABS_RZ: "clutch",
}

HAT_MAP: dict[int, str] = {
    ABS_HAT0X: "dpad_x",
    ABS_HAT0Y: "dpad_y",
}

# ---------------------------------------------------------------------------
# evdev button mapping
# ---------------------------------------------------------------------------
#: Physical button codes.  Values are standard Linux input codes; labelling
#: them by function keeps the GUI free of magic numbers.
BTN_CODES: dict[str, int] = {
    "a": 0x130,
    "b": 0x131,
    "c": 0x132,
    "x": 0x133,
    "y": 0x134,
    "z": 0x135,
    "l1": 0x136,
    "r1": 0x137,
    "l2": 0x138,
    "r2": 0x139,
    "view": 0x13A,
    "menu": 0x13B,
    "mode": 0x13C,
    "l3": 0x13D,
    "r3": 0x13E,
}

BUTTON_LABELS: dict[str, str] = {
    "a": "A",
    "b": "B",
    "c": "C",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "l1": "L1",
    "r1": "R1",
    "l2": "L2",
    "r2": "R2",
    "view": "VIEW",
    "menu": "MENU",
    "mode": "MODE",
    "l3": "L3",
    "r3": "R3",
    "dpad_up": "▲",
    "dpad_down": "▼",
    "dpad_left": "◀",
    "dpad_right": "▶",
}

#: Reverse lookup used when decoding raw evdev key events.
CODE_TO_BUTTON: dict[int, str] = {code: name for name, code in BTN_CODES.items()}

#: Paddle shifter aliases.  On the wheel, L2/R2 are the metal shift paddles
#: while the dual-clutch paddles report as L1/R1 in most kernel versions.
PADDLE_BUTTONS = frozenset({"l1", "r1", "l2", "r2"})

# ---------------------------------------------------------------------------
# Rev LED defaults
# ---------------------------------------------------------------------------
#: Number of addressable rev LEDs in the wheel's shift-light bar.  The
#: hardware protocol uses a bitmask; five segments matches the bar's physical
#: layout and can be raised in ``settings.json`` for experimentation.
LED_COUNT = 5

#: Default RPM colour bands, ordered by ascending threshold percentage.
DEFAULT_LED_BANDS: tuple[tuple[int, str, bool], ...] = (
    (0, "#21d4a0", False),
    (55, "#a8e05f", False),
    (72, "#f2c94c", False),
    (84, "#ff8a3d", False),
    (92, "#ff4d5e", True),
    (98, "#3ea6ff", True),
)

# ---------------------------------------------------------------------------
# NiceGUI-free theme tokens shared with the QSS stylesheet
# ---------------------------------------------------------------------------
COLOR_BG = "#18191c"
COLOR_SURFACE = "#202226"
COLOR_SURFACE_ALT = "#26292f"
COLOR_BORDER = "#30343c"
COLOR_TEXT = "#eef1f6"
COLOR_TEXT_MUTED = "#949aa6"
COLOR_ACCENT = "#22d3ee"
COLOR_ACCENT_SOFT = "#164e57"
COLOR_SUCCESS = "#2ee6a8"
COLOR_WARNING = "#f2c94c"
COLOR_DANGER = "#ff4d5e"

#: Filesystem locations.
CONFIG_DIR_NAME = "g923-linux-control"
