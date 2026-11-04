"""Interactive 2D rendering of the wheel and its inputs.

The widget is a pure painter: it never talks to hardware.  Pages feed it
normalized steering, pressed buttons and the current LED frame, and it draws:

* the shift-light bar with colours from the LED engine,
* a wheel rim whose top marker rotates with the steering column,
* the D-pad, face buttons, shoulder buttons, dual-clutch paddles and shift
  paddles, each highlighted while pressed.

Drawing everything with QPainter keeps the application free of image assets and
scales cleanly between window sizes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..constants import COLOR_ACCENT, COLOR_BORDER, COLOR_SURFACE_ALT, COLOR_TEXT_MUTED

RGB = tuple[int, int, int]


class WheelVisualizer(QWidget):
    """2D dashboard view of the wheel's controls."""

    def __init__(self, rotation_deg: int = 900, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation = max(270, min(900, int(rotation_deg)))
        self._steering = 0.0
        self._buttons: set[str] = set()
        self._leds: tuple[RGB | None, ...] = ()
        self._throttle = 0.0
        self._brake = 0.0
        self._clutch = 0.0
        self.setMinimumSize(520, 400)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    # -- state ------------------------------------------------------------
    def set_rotation(self, degrees: int) -> None:
        self._rotation = max(270, min(900, int(degrees)))
        self.update()

    def set_steering(self, value: float) -> None:
        self._steering = max(-1.0, min(1.0, float(value)))
        self.update()

    def set_buttons(self, buttons: Sequence[str] | set[str]) -> None:
        self._buttons = set(buttons)
        self.update()

    def set_button(self, name: str, pressed: bool) -> None:
        if pressed:
            self._buttons.add(name)
        else:
            self._buttons.discard(name)
        self.update()

    def set_leds(self, colors: Sequence[RGB | None]) -> None:
        self._leds = tuple(colors)
        self.update()

    def set_pedals(self, throttle: float, brake: float, clutch: float) -> None:
        self._throttle = max(0.0, min(1.0, float(throttle)))
        self._brake = max(0.0, min(1.0, float(brake)))
        self._clutch = max(0.0, min(1.0, float(clutch)))
        self.update()

    def reset(self) -> None:
        self._steering = 0.0
        self._buttons.clear()
        self._throttle = self._brake = self._clutch = 0.0
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(680, 470)

    # -- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        width = float(self.width())
        height = float(self.height())
        top_reserve = 54.0
        bottom_reserve = 34.0
        cx = width / 2.0
        cy = top_reserve + (height - top_reserve - bottom_reserve) / 2.0
        radius = min(width * 0.30, (height - top_reserve - bottom_reserve) * 0.43)
        radius = max(120.0, radius)

        self._draw_led_bar(painter, cx, top_reserve - 30.0, min(width * 0.62, 380.0))
        self._draw_ring(painter, cx, cy, radius)
        self._draw_center_hub(painter, cx, cy, radius)
        self._draw_face_buttons(painter, cx + radius * 0.52, cy - radius * 0.04, radius)
        self._draw_dpad(painter, cx - radius * 0.52, cy - radius * 0.04, radius)
        self._draw_shoulders(painter, cx, cy - radius, radius)
        self._draw_paddles(painter, cx, cy + radius, radius)
        self._draw_center_buttons(painter, cx, cy + radius * 0.46, radius)
        self._draw_sticks(painter, cx, cy, radius)
        painter.end()

    # -- sections ---------------------------------------------------------
    def _draw_led_bar(
        self, painter: QPainter, cx: float, y: float, total_width: float
    ) -> None:
        count = max(1, len(self._leds))
        segment_width = min(52.0, (total_width - (count - 1) * 8.0) / count)
        gap = 8.0
        strip_width = count * segment_width + (count - 1) * gap
        left = cx - strip_width / 2.0
        for index in range(count):
            rect = QRectF(left + index * (segment_width + gap), y - 8.0, segment_width, 16.0)
            color = self._leds[index] if index < len(self._leds) else None
            if color is None:
                painter.setBrush(QColor(COLOR_SURFACE_ALT))
                painter.setPen(QPen(QColor(COLOR_BORDER), 1.0))
            else:
                rgb = QColor(*color)
                glow = QColor(rgb)
                glow.setAlpha(45)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 9, 9)
                painter.setPen(QPen(rgb.lighter(125), 1.0))
                painter.setBrush(rgb)
            painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor(COLOR_TEXT_MUTED))
        caption_font = QFont(self.font())
        caption_font.setPointSizeF(7.5)
        caption_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        painter.setFont(caption_font)
        painter.drawText(
            QRectF(cx - total_width / 2.0, y - 30.0, total_width, 16.0),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "SHIFT LIGHTS",
        )

    def _draw_ring(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        outer = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#2b2f36"), radius * 0.19))
        painter.drawEllipse(outer)

        painter.setPen(QPen(QColor("#343941"), 1.2))
        painter.drawEllipse(outer.adjusted(-2, -2, 2, 2))

        # Grip markers at 9 and 3 o'clock.
        painter.setPen(QPen(QColor("#1c1e22"), radius * 0.19, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for angle in (0.0, 180.0):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.drawArc(
                QRectF(-radius, -radius, radius * 2, radius * 2),
                int(28 * 16),
                int(34 * 16),
            )
            painter.restore()

        # Rotating top marker reflects the steering column.
        angle = self._steering * (self._rotation / 2.0)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(angle)
        marker = QRectF(-5.0, -radius - 7.0, 10.0, 18.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_ACCENT))
        painter.drawRoundedRect(marker, 4, 4)
        painter.restore()

        # Steering tick labels.
        painter.setPen(QColor(COLOR_TEXT_MUTED))
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        for degrees in (-self._rotation / 2.0, 0.0, self._rotation / 2.0):
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(degrees)
            painter.drawText(
                QRectF(-30.0, -radius - 30.0, 60.0, 16.0),
                int(Qt.AlignmentFlag.AlignCenter),
                f"{int(degrees)}°",
            )
            painter.restore()

    def _draw_center_hub(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        hub_radius = radius * 0.31
        hub = QRectF(cx - hub_radius, cy - hub_radius, hub_radius * 2, hub_radius * 2)
        painter.setPen(QPen(QColor("#33373f"), 1.0))
        painter.setBrush(QColor("#1b1d21"))
        painter.drawEllipse(hub)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_ACCENT))
        painter.drawEllipse(QPointF(cx, cy - hub_radius + 8.0), 4.0, 4.0)

        angle = self._steering * (self._rotation / 2.0)
        painter.setPen(QColor("#eef1f6"))
        value_font = QFont(self.font())
        value_font.setPointSizeF(17.0)
        value_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(value_font)
        painter.drawText(
            QRectF(cx - hub_radius, cy - 20.0, hub_radius * 2, 26.0),
            int(Qt.AlignmentFlag.AlignCenter),
            f"{angle:+.0f}°",
        )

        painter.setPen(QColor(COLOR_TEXT_MUTED))
        caption_font = QFont(self.font())
        caption_font.setPointSizeF(7.0)
        caption_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
        painter.setFont(caption_font)
        painter.drawText(
            QRectF(cx - hub_radius, cy + 6.0, hub_radius * 2, 16.0),
            int(Qt.AlignmentFlag.AlignCenter),
            f"LOCK {self._rotation}°",
        )

        painter.setPen(QColor("#8b93a1"))
        painter.drawText(
            QRectF(cx - hub_radius, cy + 22.0, hub_radius * 2, 16.0),
            int(Qt.AlignmentFlag.AlignCenter),
            "STEERING",
        )

    def _draw_face_buttons(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        offset = radius * 0.17
        button_radius = radius * 0.082
        positions = {
            "y": (cx, cy - offset),
            "x": (cx - offset, cy),
            "b": (cx + offset, cy),
            "a": (cx, cy + offset),
        }
        labels = {"y": "Y", "x": "X", "b": "B", "a": "A"}
        for name, (px, py) in positions.items():
            rect = QRectF(
                px - button_radius, py - button_radius,
                button_radius * 2, button_radius * 2,
            )
            self._draw_round_button(
                painter, rect, labels[name], name in self._buttons
            )

    def _draw_dpad(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        arm = radius * 0.105
        length = radius * 0.30
        half = length / 2.0
        shapes = {
            "dpad_up": QRectF(cx - arm / 2, cy - half - arm, arm, arm),
            "dpad_down": QRectF(cx - arm / 2, cy + half, arm, arm),
            "dpad_left": QRectF(cx - half - arm, cy - arm / 2, arm, arm),
            "dpad_right": QRectF(cx + half, cy - arm / 2, arm, arm),
        }
        symbols = {
            "dpad_up": "▲",
            "dpad_down": "▼",
            "dpad_left": "◀",
            "dpad_right": "▶",
        }
        for name, rect in shapes.items():
            active = name in self._buttons
            painter.setPen(QPen(QColor(COLOR_ACCENT if active else COLOR_BORDER), 1.0))
            painter.setBrush(QColor("#123a41") if active else QColor("#23262b"))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor("#0b1c20") if active else QColor("#8b93a1"))
            font = QFont(self.font())
            font.setPointSizeF(6.5)
            painter.setFont(font)
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), symbols[name])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2a2e34"))
        center = QRectF(cx - arm / 2, cy - arm / 2, arm, arm)
        painter.drawRoundedRect(center, 2, 2)

    def _draw_shoulders(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        width = radius * 0.52
        height = radius * 0.13
        for name, direction in (("l1", -1.0), ("r1", 1.0)):
            center_x = cx + direction * radius * 0.62
            rect = QRectF(
                center_x - width / 2.0, cy + radius * 0.02, width, height
            )
            self._draw_pill_button(
                painter, rect, name.upper(), name in self._buttons
            )

    def _draw_paddles(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        width = radius * 0.17
        height = radius * 0.30
        for name, direction, label in (
            ("l2", -1.0, "L2 · DOWN"),
            ("r2", 1.0, "R2 · UP"),
        ):
            center_x = cx + direction * radius * 0.62
            rect = QRectF(center_x - width / 2.0, cy + radius * 0.10, width, height)
            active = name in self._buttons
            painter.setPen(QPen(QColor(COLOR_ACCENT if active else COLOR_BORDER), 1.0))
            painter.setBrush(QColor("#123a41") if active else QColor("#23262b"))
            painter.drawRoundedRect(rect, width / 2.4, width / 2.4)

            painter.save()
            painter.translate(rect.center())
            painter.rotate(90 if direction < 0 else -90)
            painter.setPen(QColor("#0b1c20") if active else QColor("#8b93a1"))
            font = QFont(self.font())
            font.setPointSizeF(6.5)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(
                QRectF(-height / 2, -8.0, height, 16.0),
                int(Qt.AlignmentFlag.AlignCenter),
                label,
            )
            painter.restore()

    def _draw_center_buttons(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        width = radius * 0.26
        height = radius * 0.11
        gap = radius * 0.035
        total = width * 3 + gap * 2
        for index, name in enumerate(("view", "menu", "mode")):
            left = cx - total / 2.0 + index * (width + gap)
            rect = QRectF(left, cy, width, height)
            self._draw_pill_button(
                painter, rect, name.upper(), name in self._buttons, font_size=6.0
            )

    def _draw_sticks(
        self, painter: QPainter, cx: float, cy: float, radius: float
    ) -> None:
        stick_radius = radius * 0.085
        for name, direction in (("l3", -1.0), ("r3", 1.0)):
            center = QPointF(cx + direction * radius * 0.33, cy + radius * 0.15)
            active = name in self._buttons
            painter.setPen(QPen(QColor(COLOR_ACCENT if active else COLOR_BORDER), 1.0))
            painter.setBrush(QColor("#123a41") if active else QColor("#23262b"))
            painter.drawEllipse(center, stick_radius, stick_radius)
            painter.setPen(QColor("#0b1c20") if active else QColor("#8b93a1"))
            font = QFont(self.font())
            font.setPointSizeF(6.0)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.drawText(
                QRectF(
                    center.x() - stick_radius,
                    center.y() - 8.0,
                    stick_radius * 2,
                    16.0,
                ),
                int(Qt.AlignmentFlag.AlignCenter),
                name.upper(),
            )

    # -- primitives -------------------------------------------------------
    def _draw_round_button(
        self, painter: QPainter, rect: QRectF, text: str, active: bool
    ) -> None:
        painter.setPen(QPen(QColor(COLOR_ACCENT if active else COLOR_BORDER), 1.2))
        painter.setBrush(QColor("#123a41") if active else QColor("#23262b"))
        painter.drawEllipse(rect)
        font = QFont(self.font())
        font.setPointSizeF(8.0)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#0b1c20") if active else QColor("#aab1bd"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

    def _draw_pill_button(
        self,
        painter: QPainter,
        rect: QRectF,
        text: str,
        active: bool,
        *,
        font_size: float = 7.0,
    ) -> None:
        painter.setPen(QPen(QColor(COLOR_ACCENT if active else COLOR_BORDER), 1.0))
        painter.setBrush(QColor("#123a41") if active else QColor("#23262b"))
        painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        font = QFont(self.font())
        font.setPointSizeF(font_size)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#0b1c20") if active else QColor("#aab1bd"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
