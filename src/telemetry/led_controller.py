"""Frame loop that renders the LED engine and writes the hardware bitmask.

The controller owns one :class:`QTimer`.  Each tick renders a frame at the
current rev ratio, updates the wheel only when the frame changed, and emits it
to any preview widget.  No allocation-heavy work happens per frame: colour
parsing and brightness scaling are done once per configuration change.
"""

from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config import AppSettings
from ..hardware.service import WheelService
from .led_engine import LedEngine, LedFrame

log = logging.getLogger(__name__)


class LedController(QObject):
    """Convert telemetry ratios into LED frames and hardware writes."""

    frame_ready = pyqtSignal(object)  # LedFrame

    def __init__(
        self,
        settings: AppSettings,
        wheel: WheelService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._wheel = wheel
        self._engine = LedEngine(
            settings.leds.bands,
            brightness=settings.leds.brightness,
            count=settings.leds.led_count,
            blink_hz=settings.leds.blink_hz,
        )
        self._ratio = 0.0
        self._source = "idle"
        self._last_signature: tuple[tuple[tuple[int, int, int] | None, ...], int] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(1000 / max(5, settings.leds.update_hz))))
        self._timer.timeout.connect(self._tick)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def shutdown(self) -> None:
        self._timer.stop()
        self._wheel.clear_leds()

    # -- configuration ----------------------------------------------------
    def configure(self, settings: AppSettings) -> None:
        """Adopt new band/brightness/rate settings and repaint immediately."""
        self._settings = settings
        self._engine.configure(
            settings.leds.bands,
            brightness=settings.leds.brightness,
            count=settings.leds.led_count,
            blink_hz=settings.leds.blink_hz,
        )
        interval = max(16, int(1000 / max(5, settings.leds.update_hz)))
        if interval != self._timer.interval():
            self._timer.setInterval(interval)
        self._last_signature = None
        self._tick()

    # -- input ------------------------------------------------------------
    def set_ratio(self, ratio: float, source: str = "") -> None:
        self._ratio = max(0.0, min(1.0, float(ratio)))
        if source:
            self._source = source

    @property
    def engine(self) -> LedEngine:
        return self._engine

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def source(self) -> str:
        return self._source

    def invalidate(self) -> None:
        """Resend the current frame, e.g. after the wheel reconnects."""
        self._last_signature = None
        self._tick()

    # -- frame loop -------------------------------------------------------
    def _tick(self) -> None:
        frame = self._engine.frame(self._ratio, time.monotonic())
        signature = frame.signature
        if signature == self._last_signature:
            return
        self._last_signature = signature
        self._wheel.send_led_bits(frame.bits)
        self.frame_ready.emit(frame)
