"""Pedal diagnostics and the interactive wheel visualizer."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .widgets import (
    ActionButton,
    AxisMeter,
    Card,
    SteeringReadout,
    divider,
    muted,
    page_header,
    section_title,
)
from .wheel_visualizer import WheelVisualizer

_GREEN = "#2ee6a8"
_RED = "#ff4d5e"
_BLUE = "#3ea6ff"


class PedalsPage(QWidget):
    """Real-time input diagnostics for every analogue and digital control."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation = 900
        self._values = {
            "steering": 0.0,
            "throttle": 0.0,
            "brake": 0.0,
            "clutch": 0.0,
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(
            page_header(
                "Pedals & Inputs",
                "Verify pedal travel and every button, paddle and D-pad direction "
                "as the kernel reports it.",
            )
        )

        content = QHBoxLayout()
        content.setSpacing(16)
        content.addWidget(self._build_meters_card(), 2)
        content.addWidget(self._build_visualizer_card(), 5)
        root.addLayout(content, 1)

    # -- construction -----------------------------------------------------
    def _build_meters_card(self) -> Card:
        card = Card("Pedal travel", "Auto-calibrated on connect")
        self._throttle = AxisMeter("Throttle", _GREEN)
        self._brake = AxisMeter("Brake", _RED)
        self._clutch = AxisMeter("Clutch", _BLUE)
        for meter in (self._throttle, self._brake, self._clutch):
            card.add_widget(meter)
        card.add_widget(divider())
        self._steering = SteeringReadout()
        self._steering.set_rotation(self._rotation)
        card.add_widget(self._steering)
        card.add_widget(divider())
        card.add_widget(section_title("CALIBRATION"))
        card.add_widget(
            muted(
                "Pedal polarity is sampled at rest when the wheel connects. "
                "Keep the pedals released while plugging the wheel in; replug if a "
                "pedal reads inverted."
            )
        )
        card.add_widget(
            muted(
                "Input is read passively with evdev — the wheel is never grabbed, "
                "so games keep receiving events."
            )
        )
        return card

    def _build_visualizer_card(self) -> Card:
        card = Card("Wheel inputs", "Highlights follow the kernel event stream")
        self._visualizer = WheelVisualizer(rotation_deg=self._rotation)
        card.add_widget(self._visualizer, 1)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addWidget(
            muted(
                "L2/R2 are the shift paddles; L1/R1 are the dual-clutch paddles."
            ),
            1,
        )
        reset = ActionButton("Clear highlights")
        reset.clicked.connect(self.reset_inputs)
        footer.addWidget(reset, 0)
        card.add_layout(footer)
        return card

    # -- updates ----------------------------------------------------------
    def set_rotation(self, degrees: int) -> None:
        self._rotation = max(270, min(900, int(degrees)))
        self._visualizer.set_rotation(self._rotation)
        self._steering.set_rotation(self._rotation)

    def update_axis(self, name: str, value: float) -> None:
        value = max(-1.0, min(1.0, float(value)))
        self._values[name] = value
        if name == "steering":
            self._steering.set_value(value)
            self._visualizer.set_steering(value)
            return
        if name == "throttle":
            self._throttle.set_value(value)
        elif name == "brake":
            self._brake.set_value(value)
        elif name == "clutch":
            self._clutch.set_value(value)
        self._visualizer.set_pedals(
            self._values["throttle"],
            self._values["brake"],
            self._values["clutch"],
        )

    def update_button(self, name: str, pressed: bool) -> None:
        self._visualizer.set_button(name, pressed)

    def set_buttons(self, names: set[str] | frozenset[str]) -> None:
        self._visualizer.set_buttons(names)

    def set_leds(self, colors) -> None:  # type: ignore[no-untyped-def]
        self._visualizer.set_leds(colors)

    def reset_inputs(self) -> None:
        self._values = {name: 0.0 for name in self._values}
        self._visualizer.reset()
        for meter in (self._throttle, self._brake, self._clutch):
            meter.set_value(0.0)
        self._steering.set_value(0.0)


__all__ = ["PedalsPage"]
