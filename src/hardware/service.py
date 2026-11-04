"""High-level wheel service: discovery, input streaming, driver and LEDs.

The service is the single place that owns the kernel handles.  It polls for
hot-plug every two seconds when disconnected, keeps the evdev reader alive
while connected, re-applies force-feedback settings on reconnect, and exposes
a small Qt signal surface for the GUI.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config import AppSettings
from ..constants import SUPPORTED_PRODUCTS
from .device import (
    PERMISSION_HINT,
    DeviceInfo,
    discover_devices,
    event_path_is_alive,
)
from .evdev_reader import EvdevReader
from .leds import LedSink, protocol_for_product
from .sysfs import ApplyReport, DriverSnapshot, SysfsDriver

log = logging.getLogger(__name__)

RECONNECT_INTERVAL_MS = 2000


class WheelService(QObject):
    """Bridge between the GUI and the wheel's kernel interfaces.

    Signals:
        connection_changed(bool): Wheel attached/detached.
        device_changed(object): :class:`DeviceInfo` or ``None``.
        firmware_changed(str): Firmware / USB release readout.
        axis_changed(str, float): Logical axis name and normalized value.
        button_changed(str, bool): Logical button name and pressed state.
        driver_changed(object): :class:`DriverSnapshot`.
        apply_finished(object): :class:`ApplyReport` from the last write.
        led_status_changed(str): Human-readable LED sink state.
        notice(str, str): ``(severity, message)`` where severity is one of
            ``info``/``warning``/``error``.
    """

    connection_changed = pyqtSignal(bool)
    device_changed = pyqtSignal(object)
    firmware_changed = pyqtSignal(str)
    axis_changed = pyqtSignal(str, float)
    button_changed = pyqtSignal(str, bool)
    driver_changed = pyqtSignal(object)
    apply_finished = pyqtSignal(object)
    led_status_changed = pyqtSignal(str)
    notice = pyqtSignal(str, str)

    def __init__(self, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._device: DeviceInfo | None = None
        self._reader: EvdevReader | None = None
        self._driver: SysfsDriver | None = None
        self._sink: LedSink | None = None
        self._axes: dict[str, float] = {
            "steering": 0.0,
            "throttle": 0.0,
            "brake": 0.0,
            "clutch": 0.0,
        }
        self._buttons: set[str] = set()
        self._snapshot = DriverSnapshot()
        self._last_report: ApplyReport | None = None
        self._warned: set[str] = set()
        self._led_error_reported = False
        self._initial_scan_done = False

        self._timer = QTimer(self)
        self._timer.setInterval(RECONNECT_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    # -- public state -----------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._device is not None and self._reader is not None

    @property
    def device(self) -> DeviceInfo | None:
        return self._device

    @property
    def snapshot(self) -> DriverSnapshot:
        return self._snapshot

    @property
    def last_report(self) -> ApplyReport | None:
        return self._last_report

    @property
    def axes(self) -> dict[str, float]:
        return dict(self._axes)

    @property
    def buttons(self) -> frozenset[str]:
        return frozenset(self._buttons)

    @property
    def led_status(self) -> str:
        if self._sink is None:
            return "LED output unavailable while the wheel is disconnected"
        return self._sink.status_text

    def set_settings(self, settings: AppSettings) -> None:
        """Adopt updated settings (applied on the next explicit apply)."""
        self._settings = settings

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Begin hot-plug polling and attempt an initial connection."""
        if not self._timer.isActive():
            self._timer.start()
        self._poll()

    def shutdown(self) -> None:
        """Release every kernel handle; safe to call more than once."""
        self._timer.stop()
        self._teardown("Application shutdown", notify=False)

    # -- polling ----------------------------------------------------------
    def _poll(self) -> None:
        if self._reader is not None:
            if self._device is not None and event_path_is_alive(self._device.event_path):
                self._refresh_snapshot()
                return
            self._teardown("Wheel input node disappeared.", notify=True)

        report = discover_devices()
        for warning in report.warnings:
            if warning not in self._warned:
                self._warned.add(warning)
                self.notice.emit("warning", warning)

        info = report.primary
        if info is None:
            if self._device is None:
                self._snapshot = DriverSnapshot()
            if not self._initial_scan_done:
                # Tell the UI the first scan completed so it can leave the
                # neutral "Scanning" state even when no wheel is attached.
                self._initial_scan_done = True
                self.connection_changed.emit(False)
                self.device_changed.emit(None)
                self.firmware_changed.emit("—")
                self.driver_changed.emit(self._snapshot)
            return
        self._initial_scan_done = True
        self._connect(info)

    # -- connection -------------------------------------------------------
    def _connect(self, info: DeviceInfo) -> None:
        log.info(
            "Connecting %s (%s) on %s, driver=%s",
            info.name,
            info.id_string,
            info.event_path,
            info.driver_name or "unknown",
        )
        self._device = info
        self._driver = SysfsDriver(product_id=info.product_id)
        self._sink = LedSink(
            info.hidraw_path,
            protocol_for_product(info.product_id),
            product_id=info.product_id,
        )
        if not self._sink.open():
            if not self._led_error_reported:
                self._led_error_reported = True
                self.notice.emit("warning", self._sink.status_text)
        self.led_status_changed.emit(self._sink.status_text)

        reader = EvdevReader(
            info.event_path,
            deadzone=self._settings.telemetry.throttle_deadzone,
        )
        reader.axis_changed.connect(self._on_axis)
        reader.button_changed.connect(self._on_button)
        reader.disconnected.connect(self._on_reader_disconnected)
        self._reader = reader
        reader.start()

        self._snapshot = self._driver.snapshot(refresh=True)
        self._last_report = None
        self._device_changed_emit(info)
        self._refresh_snapshot(force=True)
        self.apply_steering(silent=True)

    def _device_changed_emit(self, info: DeviceInfo | None) -> None:
        if info is None:
            self.device_changed.emit(None)
            self.firmware_changed.emit("—")
            self.connection_changed.emit(False)
            return
        self.device_changed.emit(info)
        self.firmware_changed.emit(info.firmware_display)
        self.connection_changed.emit(True)

    def _teardown(self, reason: str, notify: bool) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            try:
                reader.axis_changed.disconnect(self._on_axis)
                reader.button_changed.disconnect(self._on_button)
                reader.disconnected.disconnect(self._on_reader_disconnected)
            except TypeError:
                pass
            reader.stop()

        sink, self._sink = self._sink, None
        if sink is not None:
            sink.close()

        was_connected = self._device is not None
        self._device = None
        self._driver = None
        self._snapshot = DriverSnapshot()
        self._axes = {name: 0.0 for name in self._axes}
        for name in sorted(self._buttons):
            self.button_changed.emit(name, False)
        self._buttons.clear()

        if was_connected:
            self.connection_changed.emit(False)
            self.device_changed.emit(None)
            self.firmware_changed.emit("—")
            self.driver_changed.emit(self._snapshot)
            self.led_status_changed.emit(self.led_status)
            log.info("Wheel disconnected: %s", reason)
            if notify:
                self.notice.emit("warning", reason)

    # -- input ------------------------------------------------------------
    def _on_axis(self, name: str, value: float, _raw: int) -> None:
        self._axes[name] = value
        self.axis_changed.emit(name, value)

    def _on_button(self, name: str, pressed: bool) -> None:
        if pressed:
            self._buttons.add(name)
        else:
            self._buttons.discard(name)
        self.button_changed.emit(name, pressed)

    def _on_reader_disconnected(self, reason: str) -> None:
        if self.sender() is not self._reader:
            return
        self._teardown(reason, notify=True)

    # -- driver -----------------------------------------------------------
    def _refresh_snapshot(self, force: bool = False) -> None:
        if self._driver is None:
            if self._snapshot.available:
                self._snapshot = DriverSnapshot()
                self.driver_changed.emit(self._snapshot)
            return
        snapshot = self._driver.snapshot(refresh=force)
        if snapshot != self._snapshot:
            self._snapshot = snapshot
            self.driver_changed.emit(snapshot)

    def apply_steering(self, silent: bool = False) -> ApplyReport:
        """Push the current steering/FFB settings to the kernel driver."""
        if self._driver is None:
            report = ApplyReport(errors=("Wheel not connected",))
        else:
            self._snapshot = self._driver.snapshot(refresh=True)
            report = self._driver.apply(self._settings.steering)
            self._refresh_snapshot(force=True)

        self._last_report = report
        self.apply_finished.emit(report)

        if not silent:
            if report.errors:
                self.notice.emit("error", report.errors[0])
            elif report.unsupported:
                self.notice.emit(
                    "info",
                    "Some settings are not exposed by this kernel driver: "
                    + ", ".join(report.unsupported),
                )
            elif report.applied:
                self.notice.emit("info", report.summary)
        return report

    # -- LEDs -------------------------------------------------------------
    def send_led_bits(self, bits: int) -> bool:
        """Write an LED bitmask; returns ``False`` when no sink is available."""
        if self._sink is None:
            return False
        if self._sink.send(bits):
            return True
        message = self._sink.status_text
        if not self._led_error_reported:
            self._led_error_reported = True
            self.notice.emit("warning", message)
        self.led_status_changed.emit(message)
        return False

    def clear_leds(self) -> None:
        if self._sink is not None:
            self._sink.clear()

    # -- friendly helpers -------------------------------------------------
    @staticmethod
    def product_label(product_id: int) -> str:
        return SUPPORTED_PRODUCTS.get(product_id, f"Unknown mode ({product_id:04x})")

    @staticmethod
    def permission_hint() -> str:
        return PERMISSION_HINT
