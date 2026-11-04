"""Dashboard page: connection, live inputs and the active profile at a glance."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..config import AppSettings
from ..hardware.device import DeviceInfo
from ..hardware.sysfs import ApplyReport, DriverSnapshot
from .widgets import (
    AxisMeter,
    Card,
    KeyValueRow,
    MetricTile,
    StatusBadge,
    SteeringReadout,
    divider,
    make_label,
    muted,
    page_header,
    section_title,
)

_GREEN = "#2ee6a8"
_RED = "#ff4d5e"
_BLUE = "#3ea6ff"


class DashboardPage(QWidget):
    """Read-only overview of the wheel, its driver and the live feed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation = 900
        self._device: DeviceInfo | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(
            page_header(
                "Dashboard",
                "Kernel-level wheel status, live pedal travel and the active driving profile.",
            )
        )

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._wheel_tile = MetricTile("WHEEL", "Scanning…", "No device seen yet")
        self._steering_tile = MetricTile("STEERING", "0°", "Centred")
        self._telemetry_tile = MetricTile("TELEMETRY", "Idle", "Fallback ready")
        for tile in (self._wheel_tile, self._steering_tile, self._telemetry_tile):
            tiles.addWidget(tile, 1)
        root.addLayout(tiles)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._build_connection_card(), 1)
        content.addWidget(self._build_live_card(), 1)
        content.addWidget(self._build_profile_card(), 1)
        root.addLayout(content, 1)

        hint = muted(
            "Settings are written straight to the kernel driver — no background "
            "service is required. The driver is re-applied automatically whenever "
            "the wheel is reconnected."
        )
        hint.setContentsMargins(2, 0, 0, 0)
        root.addWidget(hint)

    # -- construction -----------------------------------------------------
    def _build_connection_card(self) -> Card:
        card = Card("Connection", "Detected hardware and driver binding")
        badge_row = QHBoxLayout()
        self._badge = StatusBadge()
        self._badge.set_status(None, "Scanning")
        badge_row.addWidget(self._badge)
        badge_row.addStretch(1)
        card.add_layout(badge_row)

        self._rows = {
            "device": KeyValueRow("Device", "—"),
            "mode": KeyValueRow("USB mode", "—"),
            "firmware": KeyValueRow("Firmware", "—"),
            "driver": KeyValueRow("Kernel driver", "—"),
            "input": KeyValueRow("Input node", "—"),
            "led": KeyValueRow("LED output", "—"),
        }
        for row in self._rows.values():
            card.add_widget(row)

        self._apply_label = muted("No settings applied yet", wrap=True)
        card.add_widget(divider())
        card.add_widget(section_title("LAST APPLY"))
        card.add_widget(self._apply_label)
        return card

    def _build_live_card(self) -> Card:
        card = Card("Live input", "Normalized travel and steering angle")
        self._steering = SteeringReadout()
        card.add_widget(self._steering)
        self._throttle = AxisMeter("Throttle", _GREEN)
        self._brake = AxisMeter("Brake", _RED)
        self._clutch = AxisMeter("Clutch", _BLUE)
        for meter in (self._throttle, self._brake, self._clutch):
            card.add_widget(meter)
        card.add_widget(divider())
        self._telemetry_status = muted("Idle · no telemetry", wrap=True)
        card.add_widget(section_title("TELEMETRY"))
        card.add_widget(self._telemetry_status)
        return card

    def _build_profile_card(self) -> Card:
        card = Card("Active profile", "Current settings applied to the wheel")
        self._profile_rows = {
            "profile": KeyValueRow("Profile", "Default"),
            "rotation": KeyValueRow("Rotation", "900°"),
            "gain": KeyValueRow("FFB gain", "100%"),
            "damper": KeyValueRow("Damper", "100%"),
            "spring": KeyValueRow("Centering spring", "100%"),
            "leds": KeyValueRow("LED brightness", "80%"),
        }
        self._profile_name = make_label("Default", "PageTitle")
        card.add_widget(self._profile_name)
        for key, row in self._profile_rows.items():
            if key == "profile":
                continue
            card.add_widget(row)
        card.add_widget(divider())
        self._fallback_row = KeyValueRow("Pedal fallback", "Enabled")
        self._hook_row = KeyValueRow("Telemetry hook", "None")
        card.add_widget(self._fallback_row)
        card.add_widget(self._hook_row)
        return card

    # -- updates ----------------------------------------------------------
    def update_device(self, info: DeviceInfo | None) -> None:
        self._device = info
        if info is None:
            self._badge.set_status(False, "Disconnected")
            self._wheel_tile.set_value("Offline")
            self._wheel_tile.set_detail("Connect the wheel over USB")
            self._rows["device"].set_value("—")
            self._rows["mode"].set_value("—")
            self._rows["driver"].set_value("—")
            self._rows["input"].set_value("—")
            return
        self._badge.set_status(True, "Detected")
        self._wheel_tile.set_value("Detected")
        self._wheel_tile.set_detail(f"{info.name} · {info.id_string}")
        self._rows["device"].set_value(info.name or "G923")
        self._rows["mode"].set_value(info.mode_label)
        self._rows["driver"].set_value(info.driver_name or "not bound")
        self._rows["input"].set_value(info.event_path)

    def update_connection(self, connected: bool) -> None:
        if not connected:
            self.update_device(None)
            self._apply_label.setText("Wheel disconnected")

    def update_firmware(self, text: str) -> None:
        self._rows["firmware"].set_value(text)

    def update_led_status(self, text: str) -> None:
        self._rows["led"].set_value(text)

    def update_driver(self, snapshot: DriverSnapshot) -> None:
        if not snapshot.available:
            self._rows["driver"].set_value("No writable attributes")
        else:
            self._rows["driver"].set_value(
                f"{snapshot.driver_name or 'kernel'} · "
                f"{'writable' if snapshot.writable else 'read-only'}"
            )

    def update_apply_report(self, report: ApplyReport) -> None:
        self._apply_label.setText(report.summary)

    def update_axis(self, name: str, value: float) -> None:
        if name == "steering":
            self._steering.set_value(value)
            angle = value * (self._rotation / 2.0)
            self._steering_tile.set_value(f"{angle:+.0f}°")
            if abs(value) < 0.02:
                self._steering_tile.set_detail("Centred")
            else:
                self._steering_tile.set_detail("Left" if value < 0 else "Right")
            return
        meter = {
            "throttle": self._throttle,
            "brake": self._brake,
            "clutch": self._clutch,
        }.get(name)
        if meter is not None:
            meter.set_value(value)

    def update_telemetry(self, status: str, source: str = "") -> None:
        self._telemetry_status.setText(status)
        if source == "telemetry":
            self._telemetry_tile.set_value("Live")
            self._telemetry_tile.set_detail("Game hook is streaming")
        elif source == "pedal":
            self._telemetry_tile.set_value("Fallback")
            self._telemetry_tile.set_detail("Throttle drives the rev LEDs")
        else:
            self._telemetry_tile.set_value("Idle")
            self._telemetry_tile.set_detail("Waiting for telemetry")

    def update_profile(self, settings: AppSettings) -> None:
        self._rotation = settings.steering.rotation_deg
        self._steering.set_rotation(self._rotation)
        self._profile_name.setText(settings.profile)
        self._profile_rows["profile"].set_value(settings.profile)
        self._profile_rows["rotation"].set_value(f"{settings.steering.rotation_deg}°")
        self._profile_rows["gain"].set_value(f"{settings.steering.ffb_gain}%")
        self._profile_rows["damper"].set_value(f"{settings.steering.damper}%")
        self._profile_rows["spring"].set_value(f"{settings.steering.spring}%")
        self._profile_rows["leds"].set_value(f"{settings.leds.brightness}%")
        self._fallback_row.set_value(
            "Enabled" if settings.leds.fallback_enabled else "Disabled"
        )

    def set_hook_name(self, name: str) -> None:
        self._hook_row.set_value(name or "None")


__all__ = ["DashboardPage"]
