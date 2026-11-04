"""Application context: owns services, settings persistence and debouncing.

The window never writes settings directly.  It calls the small mutation methods
here, which normalize values, update the relevant service, and schedule an
atomic save.  Kernel writes are debounced separately so dragging a slider does
not produce a burst of sysfs writes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer

from .config import AppSettings, LedSettings, SettingsManager, SteeringSettings
from .hardware.oversteer import OversteerBridge, OversteerStatus
from .hardware.service import WheelService
from .telemetry.led_controller import LedController
from .telemetry.service import TelemetryService

log = logging.getLogger(__name__)

_SAVE_DEBOUNCE_MS = 500
_APPLY_DEBOUNCE_MS = 150


class ApplicationContext(QObject):
    """Composition root shared by the window, tray and services."""

    def __init__(
        self,
        manager: SettingsManager,
        settings: AppSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self.settings = settings.normalized()
        self.wheel = WheelService(self.settings, parent=self)
        self.telemetry = TelemetryService(self.settings, parent=self)
        self.led_controller = LedController(self.settings, self.wheel, parent=self)
        self._started = False
        self._shutdown_done = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_now)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(_APPLY_DEBOUNCE_MS)
        self._apply_timer.timeout.connect(self._apply_driver)

        self.wheel.axis_changed.connect(self._on_axis)
        self.wheel.connection_changed.connect(self._on_wheel_connection)
        self.telemetry.ratio_changed.connect(self._on_ratio)

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Start hardware polling, telemetry and the LED frame loop."""
        if self._started:
            return
        self._started = True
        self.wheel.start()
        self.telemetry.start()
        self.led_controller.start()

    def shutdown(self) -> None:
        """Persist settings and release threads, handles and timers."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._apply_timer.stop()
        self._save_timer.stop()
        try:
            self.led_controller.shutdown()
            self.telemetry.shutdown()
            self.wheel.shutdown()
        finally:
            self._manager.save(self.settings)
            log.info("Application context shut down")

    # -- service wiring ---------------------------------------------------
    def _on_axis(self, name: str, value: float) -> None:
        if name == "throttle":
            self.telemetry.set_pedal_input(value)

    def _on_ratio(self, ratio: float, source: str) -> None:
        self.led_controller.set_ratio(ratio, source)

    def _on_wheel_connection(self, _connected: bool) -> None:
        # A fresh hidraw handle needs one full frame even when the rendered
        # bar did not change while the wheel was away.
        self.led_controller.invalidate()

    # -- persistence ------------------------------------------------------
    def schedule_save(self) -> None:
        """Persist settings after a short quiet period."""
        self._save_timer.start()

    def save_now(self) -> None:
        self._save_timer.stop()
        self._manager.save(self.settings)

    # -- settings mutations ----------------------------------------------
    def update_steering(self, steering: SteeringSettings) -> None:
        self.settings.steering = steering.normalized()
        self.wheel.set_settings(self.settings)
        self._apply_timer.start()
        self.schedule_save()

    def update_leds(self, leds: LedSettings) -> None:
        self.settings.leds = leds.normalized()
        self.telemetry.configure(self.settings)
        self.led_controller.configure(self.settings)
        self.schedule_save()

    def update_hook(self, hook_id: str) -> None:
        self.settings.telemetry.active_hook = hook_id or ""
        self.telemetry.set_active_hook(self.settings.telemetry.active_hook)
        self.telemetry.configure(self.settings)
        self.schedule_save()

    def _apply_driver(self) -> None:
        self.wheel.set_settings(self.settings)
        self.wheel.apply_steering(silent=True)

    def reapply_steering(self) -> None:
        """Push values now and surface the result in the status bar."""
        self._apply_timer.stop()
        self.wheel.set_settings(self.settings)
        self.wheel.apply_steering(silent=False)

    # -- misc actions -----------------------------------------------------
    def clear_leds(self) -> None:
        self.wheel.clear_leds()

    def export_oversteer(self) -> Path:
        """Write a portable preset next to Oversteer's profiles if present."""
        bridge = OversteerBridge()
        return bridge.export_preset(self.settings.steering, self.settings.profile)

    def oversteer_status(self) -> OversteerStatus:
        """Detection summary for the steering page footer."""
        return OversteerBridge().status()
