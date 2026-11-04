"""Persistent application settings stored in a single local JSON file.

Layout::

    ~/.config/g923-linux-control/settings.json

The file is the only state the application keeps.  It is written atomically,
with restrictive permissions, and never grows beyond a few kilobytes.  Every
value is validated on load and clamped on save, so a hand-edited or truncated
file can never crash the UI or push out-of-range values into a kernel driver.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .constants import CONFIG_DIR_NAME, DEFAULT_LED_BANDS, LED_COUNT

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_PROFILE = "Default"

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clamp(value: int, low: int, high: int) -> int:
    """Return ``value`` constrained to the inclusive ``[low, high]`` range."""
    return max(low, min(high, int(value)))


def _clamp_float(value: float, low: float, high: float) -> float:
    """Return ``value`` constrained to the inclusive ``[low, high]`` range."""
    return max(low, min(high, float(value)))


def _coerce_int(raw: Any, default: int, low: int, high: int) -> int:
    """Best-effort conversion of an untrusted JSON value to a clamped int."""
    try:
        return _clamp(int(raw), low, high)
    except (TypeError, ValueError):
        return default


def _coerce_float(raw: Any, default: float, low: float, high: float) -> float:
    """Best-effort conversion of an untrusted JSON value to a clamped float."""
    try:
        return _clamp_float(float(raw), low, high)
    except (TypeError, ValueError):
        return default


def _coerce_bool(raw: Any, default: bool) -> bool:
    """Accept JSON booleans, 0/1 and the usual textual representations."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_color(raw: Any, default: str) -> str:
    """Validate a ``#rrggbb`` colour string, falling back when malformed."""
    if isinstance(raw, str):
        candidate = raw.strip()
        if len(candidate) == 7 and candidate.startswith("#") and all(
            char in _HEX_DIGITS for char in candidate[1:]
        ):
            return candidate.lower()
    return default


def _coerce_text(raw: Any, default: str, max_length: int = 120) -> str:
    """Validate a short single-line string setting."""
    if isinstance(raw, str):
        cleaned = raw.strip().replace("\n", " ")[:max_length]
        return cleaned or default
    return default


# ---------------------------------------------------------------------------
# Nested settings groups
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class SteeringSettings:
    """Force feedback and rotation values written to the kernel driver."""

    rotation_deg: int = 900
    ffb_gain: int = 100
    damper: int = 100
    spring: int = 100

    def normalized(self) -> "SteeringSettings":
        """Return a copy with every value inside its supported range."""
        return SteeringSettings(
            rotation_deg=_clamp(self.rotation_deg, 270, 900),
            ffb_gain=_clamp(self.ffb_gain, 0, 100),
            damper=_clamp(self.damper, 0, 100),
            spring=_clamp(self.spring, 0, 100),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "rotation_deg": self.rotation_deg,
            "ffb_gain": self.ffb_gain,
            "damper": self.damper,
            "spring": self.spring,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "SteeringSettings":
        source = raw if isinstance(raw, dict) else {}
        defaults = cls()
        return cls(
            rotation_deg=_coerce_int(
                source.get("rotation_deg"), defaults.rotation_deg, 270, 900
            ),
            ffb_gain=_coerce_int(source.get("ffb_gain"), defaults.ffb_gain, 0, 100),
            damper=_coerce_int(source.get("damper"), defaults.damper, 0, 100),
            spring=_coerce_int(source.get("spring"), defaults.spring, 0, 100),
        ).normalized()


@dataclass(slots=True)
class LedBand:
    """One colour band of the rev-light bar, keyed by RPM percentage."""

    threshold: int = 0
    color: str = "#21d4a0"
    flash: bool = False

    def normalized(self) -> "LedBand":
        return LedBand(
            threshold=_clamp(self.threshold, 0, 100),
            color=_coerce_color(self.color, "#21d4a0"),
            flash=bool(self.flash),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "color": self.color,
            "flash": self.flash,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "LedBand":
        source = raw if isinstance(raw, dict) else {}
        defaults = cls()
        return cls(
            threshold=_coerce_int(source.get("threshold"), defaults.threshold, 0, 100),
            color=_coerce_color(source.get("color"), defaults.color),
            flash=_coerce_bool(source.get("flash"), defaults.flash),
        )


def default_led_bands() -> list[LedBand]:
    """Build the stock green → amber → red → flashing blue band list."""
    return [
        LedBand(threshold=threshold, color=color, flash=flash)
        for threshold, color, flash in DEFAULT_LED_BANDS
    ]


@dataclass(slots=True)
class LedSettings:
    """Rev-light appearance and fallback behaviour."""

    brightness: int = 80
    bands: list[LedBand] = field(default_factory=default_led_bands)
    fallback_enabled: bool = True
    blink_hz: float = 6.0
    update_hz: int = 30
    led_count: int = LED_COUNT

    def normalized(self) -> "LedSettings":
        bands = sorted(
            (band.normalized() for band in self.bands if isinstance(band, LedBand)),
            key=lambda band: band.threshold,
        )
        if not bands:
            bands = default_led_bands()
        # A band list without a 0% entry would leave the lowest revs dark.
        if bands[0].threshold != 0:
            bands.insert(0, LedBand(threshold=0, color=bands[0].color))
        return LedSettings(
            brightness=_clamp(self.brightness, 0, 100),
            bands=bands,
            fallback_enabled=bool(self.fallback_enabled),
            blink_hz=_clamp_float(self.blink_hz, 0.5, 20.0),
            update_hz=_clamp(self.update_hz, 5, 60),
            led_count=_clamp(self.led_count, 1, 16),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "brightness": self.brightness,
            "bands": [band.to_dict() for band in self.bands],
            "fallback_enabled": self.fallback_enabled,
            "blink_hz": self.blink_hz,
            "update_hz": self.update_hz,
            "led_count": self.led_count,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "LedSettings":
        source = raw if isinstance(raw, dict) else {}
        defaults = cls()
        raw_bands = source.get("bands")
        bands: list[LedBand] = []
        if isinstance(raw_bands, list):
            bands = [LedBand.from_dict(item) for item in raw_bands[:16]]
        return cls(
            brightness=_coerce_int(
                source.get("brightness"), defaults.brightness, 0, 100
            ),
            bands=bands or default_led_bands(),
            fallback_enabled=_coerce_bool(
                source.get("fallback_enabled"), defaults.fallback_enabled
            ),
            blink_hz=_coerce_float(source.get("blink_hz"), defaults.blink_hz, 0.5, 20.0),
            update_hz=_coerce_int(source.get("update_hz"), defaults.update_hz, 5, 60),
            led_count=_coerce_int(
                source.get("led_count"), defaults.led_count, 1, 16
            ),
        ).normalized()


@dataclass(slots=True)
class TelemetrySettings:
    """Hook selection and input-fallback behaviour."""

    active_hook: str = ""
    #: 0 means "use the interval declared by the hook"; a non-zero value
    #: overrides every hook (advanced tuning from settings.json only).
    poll_interval_ms: int = 0
    stale_timeout_ms: int = 800
    throttle_deadzone: float = 0.02
    max_rpm: int = 8000

    def normalized(self) -> "TelemetrySettings":
        return TelemetrySettings(
            active_hook=_coerce_text(self.active_hook, "", 200),
            poll_interval_ms=_clamp(self.poll_interval_ms, 0, 1000),
            stale_timeout_ms=_clamp(self.stale_timeout_ms, 100, 10_000),
            throttle_deadzone=_clamp_float(self.throttle_deadzone, 0.0, 0.5),
            max_rpm=_clamp(self.max_rpm, 1000, 20_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_hook": self.active_hook,
            "poll_interval_ms": self.poll_interval_ms,
            "stale_timeout_ms": self.stale_timeout_ms,
            "throttle_deadzone": self.throttle_deadzone,
            "max_rpm": self.max_rpm,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "TelemetrySettings":
        source = raw if isinstance(raw, dict) else {}
        defaults = cls()
        return cls(
            active_hook=_coerce_text(
                source.get("active_hook"), defaults.active_hook, 200
            ),
            poll_interval_ms=_coerce_int(
                source.get("poll_interval_ms"), defaults.poll_interval_ms, 0, 1000
            ),
            stale_timeout_ms=_coerce_int(
                source.get("stale_timeout_ms"), defaults.stale_timeout_ms, 100, 10_000
            ),
            throttle_deadzone=_coerce_float(
                source.get("throttle_deadzone"),
                defaults.throttle_deadzone,
                0.0,
                0.5,
            ),
            max_rpm=_coerce_int(
                source.get("max_rpm"), defaults.max_rpm, 1000, 20_000
            ),
        ).normalized()


@dataclass(slots=True)
class UiSettings:
    """Window and tray preferences."""

    close_to_tray: bool = True
    start_minimized: bool = False
    last_page: str = "dashboard"
    window_width: int = 1180
    window_height: int = 780

    def normalized(self) -> "UiSettings":
        return UiSettings(
            close_to_tray=bool(self.close_to_tray),
            start_minimized=bool(self.start_minimized),
            last_page=_coerce_text(self.last_page, "dashboard", 32),
            window_width=_clamp(self.window_width, 900, 3840),
            window_height=_clamp(self.window_height, 620, 2160),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "close_to_tray": self.close_to_tray,
            "start_minimized": self.start_minimized,
            "last_page": self.last_page,
            "window_width": self.window_width,
            "window_height": self.window_height,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "UiSettings":
        source = raw if isinstance(raw, dict) else {}
        defaults = cls()
        return cls(
            close_to_tray=_coerce_bool(
                source.get("close_to_tray"), defaults.close_to_tray
            ),
            start_minimized=_coerce_bool(
                source.get("start_minimized"), defaults.start_minimized
            ),
            last_page=_coerce_text(source.get("last_page"), defaults.last_page, 32),
            window_width=_coerce_int(
                source.get("window_width"), defaults.window_width, 900, 3840
            ),
            window_height=_coerce_int(
                source.get("window_height"), defaults.window_height, 620, 2160
            ),
        ).normalized()


# ---------------------------------------------------------------------------
# Root document
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class AppSettings:
    """Complete, validated application configuration."""

    schema: int = SCHEMA_VERSION
    profile: str = DEFAULT_PROFILE
    steering: SteeringSettings = field(default_factory=SteeringSettings)
    leds: LedSettings = field(default_factory=LedSettings)
    telemetry: TelemetrySettings = field(default_factory=TelemetrySettings)
    ui: UiSettings = field(default_factory=UiSettings)

    def normalized(self) -> "AppSettings":
        return AppSettings(
            schema=SCHEMA_VERSION,
            profile=_coerce_text(self.profile, DEFAULT_PROFILE, 60),
            steering=self.steering.normalized(),
            leds=self.leds.normalized(),
            telemetry=self.telemetry.normalized(),
            ui=self.ui.normalized(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "profile": self.profile,
            "steering": self.steering.to_dict(),
            "leds": self.leds.to_dict(),
            "telemetry": self.telemetry.to_dict(),
            "ui": self.ui.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "AppSettings":
        if not isinstance(raw, dict):
            raise ValueError("settings root must be a JSON object")
        defaults = cls()
        return cls(
            schema=SCHEMA_VERSION,
            profile=_coerce_text(raw.get("profile"), defaults.profile, 60),
            steering=SteeringSettings.from_dict(raw.get("steering")),
            leds=LedSettings.from_dict(raw.get("leds")),
            telemetry=TelemetrySettings.from_dict(raw.get("telemetry")),
            ui=UiSettings.from_dict(raw.get("ui")),
        ).normalized()


def default_settings() -> AppSettings:
    """Return a fully populated default configuration."""
    return AppSettings().normalized()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def default_config_dir() -> Path:
    """Resolve the XDG configuration directory for this application."""
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_home).expanduser() if xdg_home else Path.home() / ".config"
    return base / CONFIG_DIR_NAME


class SettingsManager:
    """Load and atomically persist :class:`AppSettings`."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_dir() / "settings.json"

    # -- reading ----------------------------------------------------------
    def load(self) -> AppSettings:
        """Read the settings file, returning defaults when it is unusable."""
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return default_settings()
        except OSError as exc:
            log.warning("Could not read %s: %s — using defaults", self.path, exc)
            return default_settings()

        try:
            document = json.loads(raw_text)
            return AppSettings.from_dict(document)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            log.warning("Invalid settings in %s (%s) — using defaults", self.path, exc)
            self._quarantine()
            return default_settings()

    def _quarantine(self) -> None:
        """Keep a corrupt file around for debugging instead of overwriting it."""
        backup = self.path.with_suffix(".json.bak")
        try:
            self.path.replace(backup)
            log.info("Moved unreadable settings to %s", backup)
        except OSError as exc:  # pragma: no cover - best effort only
            log.debug("Could not back up invalid settings: %s", exc)

    # -- writing ----------------------------------------------------------
    def save(self, settings: AppSettings) -> None:
        """Atomically write ``settings`` as pretty-printed UTF-8 JSON."""
        document = settings.normalized().to_dict()
        payload = json.dumps(document, indent=2, sort_keys=False) + "\n"

        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # The temporary file lives beside the target so os.replace() is
            # atomic on the same filesystem.
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".settings-",
                suffix=".tmp",
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                with handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temp_path, 0o600)
                os.replace(temp_path, self.path)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
        except OSError as exc:
            log.error("Could not save settings to %s: %s", self.path, exc)

    def reset(self) -> AppSettings:
        """Restore defaults and persist them."""
        settings = default_settings()
        self.save(settings)
        return settings


# ---------------------------------------------------------------------------
# Small mutation helpers used by the GUI
# ---------------------------------------------------------------------------
def replace_settings(settings: AppSettings, **changes: Any) -> AppSettings:
    """Return a normalized copy of ``settings`` with top-level fields replaced."""
    return replace(settings, **changes).normalized()


def ensure_band_order(bands: Iterable[LedBand]) -> list[LedBand]:
    """Sort and normalize ``bands`` so the LED engine can consume them."""
    return sorted((band.normalized() for band in bands), key=lambda b: b.threshold)
