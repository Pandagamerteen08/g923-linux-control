"""Steering and force-feedback page."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..config import SteeringSettings
from ..hardware.sysfs import ApplyReport, DriverSnapshot
from .widgets import (
    ActionButton,
    Card,
    KeyValueRow,
    SliderRow,
    divider,
    muted,
    page_header,
    section_title,
)


class SteeringPage(QWidget):
    """Rotation and force-feedback controls backed by sysfs writes.

    Signals:
        steering_changed(object): Emitted with a new
            :class:`SteeringSettings` on every slider movement.  The window
            debounces persistence and kernel writes.
        reapply_requested(): User asked to push the current values again.
        export_requested(): User asked to export an Oversteer preset.
    """

    steering_changed = pyqtSignal(object)
    reapply_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = SteeringSettings()
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(
            page_header(
                "Steering & Force Feedback",
                "Adjust the hardware lock and FFB character. Writes go directly to "
                "hid-lg4ff / new-lg4ff attributes without restarting games.",
            )
        )

        columns = QHBoxLayout()
        columns.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._build_rotation_card())
        left.addWidget(self._build_ffb_card())
        columns.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._build_driver_card())
        right.addWidget(self._build_notes_card())
        columns.addLayout(right, 2)
        right.addStretch(1)

        root.addLayout(columns, 1)

    # -- construction -----------------------------------------------------
    def _build_rotation_card(self) -> Card:
        card = Card(
            "Operating range",
            "Physical lock-to-lock rotation reported to games",
        )
        self._rotation = SliderRow(
            "Degrees of rotation",
            270,
            900,
            self._settings.rotation_deg,
            suffix="°",
            step=10,
            description=(
                "270°–540° suits formula and rally cars; 900° gives road cars the "
                "full range. Applied immediately through the driver's range attribute."
            ),
        )
        self._rotation.valueChanged.connect(self._emit_changes)
        card.add_widget(self._rotation)
        return card

    def _build_ffb_card(self) -> Card:
        card = Card("Force feedback", "Gain and conditional effect strengths")
        self._gain = SliderRow(
            "Overall gain",
            0,
            100,
            self._settings.ffb_gain,
            suffix="%",
            description="Scales every force the game sends to the wheel.",
        )
        self._damper = SliderRow(
            "Damper strength",
            0,
            100,
            self._settings.damper,
            suffix="%",
            description="Resistance proportional to steering speed; calms snap oversteer.",
        )
        self._spring = SliderRow(
            "Centering spring",
            0,
            100,
            self._settings.spring,
            suffix="%",
            description="Return-to-centre force. Set to 0 for raw game-driven feedback.",
        )
        for row in (self._gain, self._damper, self._spring):
            row.valueChanged.connect(self._emit_changes)
            card.add_widget(row)
        return card

    def _build_driver_card(self) -> Card:
        card = Card("Kernel integration", "Live driver capability probe")
        self._driver_rows = {
            "driver": KeyValueRow("Driver", "—"),
            "control": KeyValueRow("Control node", "—"),
            "attributes": KeyValueRow("Attributes", "—"),
            "access": KeyValueRow("Access", "—"),
            "oversteer": KeyValueRow("Oversteer", "—"),
        }
        for row in self._driver_rows.values():
            card.add_widget(row)
        card.add_widget(divider())
        card.add_widget(section_title("LAST APPLY"))
        self._report = muted("No settings applied yet")
        card.add_widget(self._report)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._apply_button = ActionButton("Apply again", variant="primary")
        self._apply_button.clicked.connect(self.reapply_requested.emit)
        self._export_button = ActionButton("Export Oversteer preset")
        self._export_button.setToolTip(
            "Write a portable JSON preset that mirrors these values for Oversteer users."
        )
        self._export_button.clicked.connect(self.export_requested.emit)
        buttons.addWidget(self._apply_button)
        buttons.addWidget(self._export_button)
        card.add_layout(buttons)
        return card

    def _build_notes_card(self) -> Card:
        card = Card("Driver notes", "What the kernel exposes")
        note = muted(
            "Rotation is the only attribute exposed by some HID++ bindings. "
            "Gain, damper and spring require hid-lg4ff or the new-lg4ff module. "
            "Unsupported values are skipped and reported above instead of failing "
            "the whole apply.",
        )
        card.add_widget(note)
        card.add_widget(divider())
        hint = muted(
            "Write access usually requires the wheel's udev rule to grant your user "
            "the input group. The README contains a ready-to-use rule."
        )
        card.add_widget(hint)
        return card

    # -- state ------------------------------------------------------------
    def load(self, settings: SteeringSettings) -> None:
        """Populate the sliders without emitting change signals."""
        self._loading = True
        try:
            self._settings = settings.normalized()
            self._rotation.set_value(self._settings.rotation_deg)
            self._gain.set_value(self._settings.ffb_gain)
            self._damper.set_value(self._settings.damper)
            self._spring.set_value(self._settings.spring)
        finally:
            self._loading = False

    def _emit_changes(self, _value: int | None = None) -> None:
        if self._loading:
            return
        self._settings = SteeringSettings(
            rotation_deg=self._rotation.value(),
            ffb_gain=self._gain.value(),
            damper=self._damper.value(),
            spring=self._spring.value(),
        ).normalized()
        self.steering_changed.emit(self._settings)

    # -- updates ----------------------------------------------------------
    def set_connected(self, connected: bool) -> None:
        self._apply_button.setEnabled(connected)
        self._export_button.setEnabled(True)

    def update_driver(self, snapshot: DriverSnapshot) -> None:
        self._driver_rows["driver"].set_value(snapshot.driver_name or "—")
        self._driver_rows["control"].set_value(snapshot.control_dir or "—")
        self._driver_rows["attributes"].set_value(
            ", ".join(snapshot.attributes) if snapshot.attributes else "none"
        )
        if not snapshot.available:
            self._driver_rows["access"].set_value("unavailable")
        else:
            self._driver_rows["access"].set_value(
                "writable" if snapshot.writable else "read-only"
            )

    def set_oversteer_status(self, text: str) -> None:
        self._driver_rows["oversteer"].set_value(text)

    def set_report(self, report: ApplyReport) -> None:
        self._report.setText(report.summary)
        self._report.setObjectName("ErrorText" if report.errors else "Muted")
        style = self._report.style()
        if style is not None:
            style.unpolish(self._report)
            style.polish(self._report)
        self._report.setToolTip(report.summary)

    def update_rotation_display(self, settings: SteeringSettings) -> None:
        """Keep the page in sync when settings change elsewhere."""
        self.load(settings)
