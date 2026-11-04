"""Rev-LED rendering: GPU-free, deterministic and unit-testable.

The engine converts a 0.0–1.0 rev ratio into a :class:`LedFrame` containing an
RGB colour per segment (for the on-screen bar) and a bitmask (for the wheel).
Colour bands come from the user's settings; a band may flash, which toggles the
whole lit bar at ``blink_hz``.

Keeping the rendering free of Qt makes the LED behaviour reproducible in tests
and lets the preview in the settings page reuse exactly the same code path as
the hardware output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..config import LedBand

RGB = tuple[int, int, int]

_MAX_HARDWARE_BITS = 0xFF


def parse_color(value: str, fallback: RGB = (33, 212, 160)) -> RGB:
    """Convert ``#rrggbb`` to an RGB tuple, falling back on malformed input."""
    try:
        text = value.lstrip("#")
        if len(text) != 6:
            return fallback
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except (ValueError, AttributeError):
        return fallback


def scale_color(color: RGB, brightness: float) -> RGB:
    """Scale an RGB colour by a 0.0–1.0 brightness factor."""
    factor = max(0.0, min(1.0, brightness))
    return tuple(int(channel * factor) for channel in color)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class LedFrame:
    """One rendered LED frame.

    Attributes:
        colors: One entry per segment, ``None`` when the segment is dark.
        bits: Bitmask for the wheel's monochrome rev bar.
        lit: Number of illuminated segments.
        band_index: Index of the active colour band, for UI annotations.
        flashing: Whether the active band is currently in its dark phase.
    """

    colors: tuple[RGB | None, ...]
    bits: int
    lit: int
    band_index: int = 0
    flashing: bool = False

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.colors)

    @property
    def signature(self) -> tuple[tuple[RGB | None, ...], int]:
        """Comparable value used to suppress redundant repaints/writes."""
        return (self.colors, self.bits)


class LedEngine:
    """Turn a rev ratio into LED frames."""

    def __init__(
        self,
        bands: Sequence[LedBand],
        brightness: int = 80,
        count: int = 5,
        blink_hz: float = 6.0,
    ) -> None:
        self.configure(bands, brightness, count, blink_hz)

    def configure(
        self,
        bands: Sequence[LedBand],
        brightness: int = 80,
        count: int = 5,
        blink_hz: float = 6.0,
    ) -> None:
        """Replace the band table and rendering parameters."""
        normalized: list[LedBand] = []
        for band in bands:
            normalized.append(band.normalized())
        normalized.sort(key=lambda band: band.threshold)
        if not normalized:
            normalized = [LedBand(threshold=0, color="#21d4a0")]
        if normalized[0].threshold != 0:
            normalized.insert(
                0, LedBand(threshold=0, color=normalized[0].color)
            )
        self._bands = normalized
        self._brightness = max(0, min(100, int(brightness))) / 100.0
        self._count = max(1, min(16, int(count)))
        self._blink_hz = max(0.1, float(blink_hz))

    @property
    def count(self) -> int:
        return self._count

    @property
    def bands(self) -> tuple[LedBand, ...]:
        return tuple(self._bands)

    def frame(self, ratio: float, now: float) -> LedFrame:
        """Render the bar for ``ratio`` at monotonic time ``now`` (seconds)."""
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = 0.0
        ratio = max(0.0, min(1.0, ratio))
        percent = ratio * 100.0

        band_index = 0
        for index, band in enumerate(self._bands):
            if percent >= band.threshold:
                band_index = index
        band = self._bands[band_index]

        # Ceiling keeps the bar progressive: any pressure lights the first
        # segment, and 50% of a five-segment bar lights three, not two.
        lit = math.ceil(ratio * self._count) if ratio > 0.0 else 0

        flashing_off = False
        if band.flash and lit:
            period = 1.0 / self._blink_hz
            phase = (now % period) / period
            flashing_off = phase >= 0.5

        color = scale_color(parse_color(band.color), self._brightness)
        colors: list[RGB | None] = []
        for index in range(self._count):
            if index < lit and not flashing_off:
                colors.append(color)
            else:
                colors.append(None)

        bits = 0
        if not flashing_off:
            for index in range(lit):
                bits |= 1 << index
        bits &= _MAX_HARDWARE_BITS
        return LedFrame(
            colors=tuple(colors),
            bits=bits,
            lit=lit if not flashing_off else 0,
            band_index=band_index,
            flashing=flashing_off,
        )

    def preview(self, percent: float, now: float = 0.0) -> LedFrame:
        """Convenience wrapper accepting a 0–100 percentage."""
        return self.frame(percent / 100.0, now)


def bands_brief(bands: Iterable[LedBand]) -> str:
    """Compact description such as ``0% teal · 72% yellow · 92% red flash``."""
    parts = []
    for band in bands:
        flash = " flash" if band.flash else ""
        parts.append(f"{band.threshold}% {band.color}{flash}")
    return " · ".join(parts)


def flash_period_seconds(blink_hz: float) -> float:
    """Full on/off period for a blink frequency."""
    return 1.0 / max(0.1, blink_hz)


def duty_cycle(now: float, blink_hz: float) -> float:
    """Return the position within the blink cycle (0.0–1.0)."""
    return (now % flash_period_seconds(blink_hz)) / flash_period_seconds(blink_hz)


# ``math`` is imported for callers that want a smooth pulse; keeping the symbol
# here avoids re-deriving the formula in the UI.
def smooth_pulse(now: float, blink_hz: float) -> float:
    """Return a 0–1 sinusoidal brightness factor for optional soft blinking."""
    return (math.sin(2 * math.pi * blink_hz * now) + 1.0) / 2.0
