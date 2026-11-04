"""Pedal-to-LED fallback mapping.

When no game provides telemetry, the throttle pedal can drive the rev bar so
the lights still behave like a shift indicator.  The mapper is deliberately
simple and predictable: deadzone, linear travel, light exponential smoothing
to stop the bar flickering on noisy potentiometers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PedalFallback:
    """Convert throttle travel to a 0.0–1.0 LED ratio."""

    deadzone: float = 0.02
    smoothing: float = 0.45
    _value: float = 0.0

    def __post_init__(self) -> None:
        self.deadzone = max(0.0, min(0.5, float(self.deadzone)))
        self.smoothing = max(0.05, min(0.95, float(self.smoothing)))

    def reset(self) -> None:
        """Drop the smoothed value, e.g. when the wheel disconnects."""
        self._value = 0.0

    def map(self, throttle: float) -> float:
        """Return a smoothed LED ratio for normalized throttle travel."""
        try:
            raw = float(throttle)
        except (TypeError, ValueError):
            raw = 0.0
        raw = max(0.0, min(1.0, raw))
        if raw <= self.deadzone:
            target = 0.0
        else:
            target = (raw - self.deadzone) / max(1e-6, 1.0 - self.deadzone)
        target = max(0.0, min(1.0, target))
        # Rise quickly (the driver expects immediate feedback) and fall a bit
        # more slowly, which reads as a natural "rev hang".
        alpha = self.smoothing if target > self._value else min(0.9, self.smoothing + 0.2)
        self._value += (target - self._value) * alpha
        if self._value < 0.005:
            self._value = 0.0
        return self._value

    @property
    def value(self) -> float:
        return self._value


def throttle_ratio(throttle: float, deadzone: float = 0.02) -> float:
    """Stateless mapping helper used in tests and the UI."""
    mapper = PedalFallback(deadzone=deadzone, smoothing=1.0)
    return mapper.map(throttle)
