"""Reusable widgets for the dashboard.

All widgets are deliberately small and dependency-free beyond PyQt6; visual
consistency comes from object names styled in ``assets/style.qss`` and from a
handful of painted components (badge, LED strip, level bars).
"""

from __future__ import annotations

from typing import Iterable, Sequence

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_SURFACE_ALT,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
)

RGB = tuple[int, int, int]


# ---------------------------------------------------------------------------
# Small builders
# ---------------------------------------------------------------------------
def make_label(
    text: str = "",
    object_name: str = "",
    *,
    word_wrap: bool = False,
    parent: QWidget | None = None,
) -> QLabel:
    """Create a label, optionally styled by QSS object name."""
    label = QLabel(text, parent)
    if object_name:
        label.setObjectName(object_name)
    label.setWordWrap(word_wrap)
    return label


def section_title(text: str) -> QLabel:
    return make_label(text.upper(), "SectionTitle")


def muted(text: str, *, wrap: bool = True) -> QLabel:
    return make_label(text, "Muted", word_wrap=wrap)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def page_header(title: str, subtitle: str) -> QWidget:
    """Title block shared by every page."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(make_label(title, "PageTitle"))
    layout.addWidget(make_label(subtitle, "PageSubtitle", word_wrap=True))
    return box


class Card(QFrame):
    """Rounded surface that hosts a titled group of controls."""

    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        *,
        accent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CardAccent" if accent else "Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 18)
        self._layout.setSpacing(12)
        self.header: QHBoxLayout | None = None

        if title:
            header = QHBoxLayout()
            header.setSpacing(8)
            header.setContentsMargins(0, 0, 0, 0)
            text_column = QVBoxLayout()
            text_column.setSpacing(2)
            text_column.addWidget(make_label(title, "CardTitle"))
            if subtitle:
                text_column.addWidget(muted(subtitle))
            header.addLayout(text_column, 1)
            self.header = header
            self._layout.addLayout(header)

    @property
    def body(self) -> QVBoxLayout:
        """Layout that page code appends content to."""
        return self._layout

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self._layout.addLayout(layout)

    def add_header_action(self, widget: QWidget) -> None:
        """Add a compact action aligned with the card title."""
        if self.header is None:
            return
        self.header.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)


# ---------------------------------------------------------------------------
# Status badge
# ---------------------------------------------------------------------------
class StatusBadge(QWidget):
    """Pill-shaped connection indicator with a coloured, softly glowing dot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = "Checking"
        self._online: bool | None = None
        self._color = QColor(COLOR_TEXT_MUTED)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._apply_state()

    def _apply_state(self) -> None:
        if self._online is True:
            self._color = QColor(COLOR_SUCCESS)
        elif self._online is False:
            self._color = QColor(COLOR_DANGER)
        else:
            self._color = QColor(COLOR_WARNING)
        self.updateGeometry()
        self.update()

    def set_status(self, online: bool | None, text: str) -> None:
        """Set ``online`` to ``None`` while the first scan is running."""
        self._online = online
        self._text = text
        self.setToolTip(text)
        self._apply_state()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = QFontMetrics(self.font())
        return QSize(metrics.horizontalAdvance(self._text) + 52, 30)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

        background = QColor(self._color)
        background.setAlpha(28)
        border = QColor(self._color)
        border.setAlpha(90)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 15, 15)

        dot_center = rect.center()
        dot_center.setX(rect.left() + 17.0)
        glow = QColor(self._color)
        glow.setAlpha(48)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(dot_center, 8.0, 8.0)
        painter.setBrush(self._color)
        painter.drawEllipse(dot_center, 4.0, 4.0)

        painter.setPen(QColor(COLOR_TEXT))
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        font.setPointSizeF(9.0)
        painter.setFont(font)
        text_rect = rect.adjusted(32.0, 0.0, -12.0, 0.0)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._text,
        )
        painter.end()


# ---------------------------------------------------------------------------
# LED preview strip
# ---------------------------------------------------------------------------
class LedStrip(QWidget):
    """Rounded LED segments rendered from an engine frame."""

    def __init__(
        self,
        count: int = 5,
        *,
        height: int = 34,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._count = max(1, count)
        self._colors: tuple[RGB | None, ...] = tuple(None for _ in range(self._count))
        self._segment_height = 16
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_count(self, count: int) -> None:
        self._count = max(1, int(count))
        self._colors = tuple(None for _ in range(self._count))
        self.updateGeometry()
        self.update()

    def set_colors(self, colors: Sequence[RGB | None]) -> None:
        """Update the displayed frame; extra/missing entries are tolerated."""
        normalized: list[RGB | None] = []
        for index in range(self._count):
            value = colors[index] if index < len(colors) else None
            normalized.append(tuple(value) if value is not None else None)  # type: ignore[arg-type]
        self._colors = tuple(normalized)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        spacing = 8.0
        side_margin = 4.0
        segment_width = max(
            12.0,
            (width - side_margin * 2 - spacing * (self._count - 1)) / self._count,
        )
        y = (self.height() - self._segment_height) / 2.0
        radius = self._segment_height / 2.0

        for index, color in enumerate(self._colors):
            x = side_margin + index * (segment_width + spacing)
            rect = QRectF(x, y, segment_width, float(self._segment_height))
            if color is None:
                painter.setPen(QPen(QColor(COLOR_BORDER), 1.0))
                painter.setBrush(QColor(COLOR_SURFACE_ALT))
                painter.drawRoundedRect(rect, radius, radius)
                continue
            rgb = QColor(*color)
            glow = QColor(rgb)
            glow.setAlpha(55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(rect.adjusted(-2.0, -2.0, 2.0, 2.0), radius + 2, radius + 2)
            painter.setPen(QPen(rgb.lighter(130), 1.0))
            painter.setBrush(rgb)
            painter.drawRoundedRect(rect, radius, radius)
        painter.end()


# ---------------------------------------------------------------------------
# Level bars / axis meters
# ---------------------------------------------------------------------------
class LevelBar(QWidget):
    """A slim, gradient-filled horizontal meter."""

    def __init__(
        self,
        color: str = COLOR_ACCENT,
        *,
        height: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._color = QColor(color)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.height() / 2.0
        track = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_SURFACE_ALT))
        painter.drawRoundedRect(track, radius, radius)

        if self._value > 0.0:
            width = max(float(self.height()), track.width() * self._value)
            fill = QRectF(0.0, 0.0, width, track.height())
            gradient = QLinearGradient(fill.topLeft(), fill.topRight())
            start = QColor(self._color)
            start.setAlpha(165)
            gradient.setColorAt(0.0, start)
            gradient.setColorAt(1.0, self._color)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(fill, radius, radius)
        painter.end()


class AxisMeter(QWidget):
    """Label + percentage + bar for one pedal axis."""

    def __init__(
        self,
        title: str,
        color: str = COLOR_ACCENT,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(make_label(title, "Value"), 1)
        self._value_label = make_label("0%", "AccentValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._value_label, 0)
        layout.addLayout(header)

        self._bar = LevelBar(color)
        layout.addWidget(self._bar)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._bar.set_value(value)
        self._value_label.setText(f"{value * 100:.0f}%")

    def set_color(self, color: str) -> None:
        self._bar.set_color(color)


class SteeringReadout(QWidget):
    """Signed steering angle with a centered bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation = 900
        self._steering = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(make_label("Steering", "Value"), 1)
        self._value_label = make_label("0°", "AccentValue")
        header.addWidget(self._value_label, 0)
        layout.addLayout(header)

        self._bar = LevelBar(COLOR_ACCENT)
        layout.addWidget(self._bar)

    def set_rotation(self, degrees: int) -> None:
        self._rotation = max(270, min(900, int(degrees)))

    def set_value(self, value: float) -> None:
        self._steering = max(-1.0, min(1.0, float(value)))
        angle = self._steering * (self._rotation / 2.0)
        self._value_label.setText(f"{angle:+.0f}°")
        self._bar.set_value(abs(self._steering))


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------
class SliderRow(QWidget):
    """Labelled slider with a live value readout and optional hint."""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        *,
        suffix: str = "",
        step: int = 1,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._suffix = suffix
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(make_label(title, "Value"), 1)
        self._value_label = make_label("", "AccentValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self._value_label, 0)
        layout.addLayout(header)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(max(step, (maximum - minimum) // 10))
        self._slider.setValue(value)
        self._slider.valueChanged.connect(self._on_value_changed)
        layout.addWidget(self._slider)

        if description:
            layout.addWidget(muted(description, wrap=True))

        self._update_label(value)

    def _update_label(self, value: int) -> None:
        self._value_label.setText(f"{value}{self._suffix}")

    def _on_value_changed(self, value: int) -> None:
        self._update_label(value)
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self._slider.value()

    def set_value(self, value: int, *, emit: bool = False) -> None:
        blocked = self._slider.blockSignals(not emit)
        try:
            self._slider.setValue(int(value))
        finally:
            self._slider.blockSignals(blocked)
        self._update_label(self._slider.value())

    def slider(self) -> QSlider:
        return self._slider


class ToggleRow(QWidget):
    """Checkbox with a title and an explanatory line."""

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        description: str = "",
        *,
        checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._checkbox = QCheckBox(title)
        self._checkbox.setChecked(checked)
        self._checkbox.toggled.connect(self.toggled.emit)
        layout.addWidget(self._checkbox)
        if description:
            hint = muted(description)
            hint.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(hint)

    def isChecked(self) -> bool:  # noqa: N802 - Qt naming
        return self._checkbox.isChecked()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt naming
        self._checkbox.setChecked(bool(checked))

    def checkbox(self) -> QCheckBox:
        return self._checkbox


class KeyValueRow(QWidget):
    """Two-column read-only row for status tables."""

    def __init__(
        self,
        key: str,
        value: str = "—",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(muted(key, wrap=False), 0)
        layout.addStretch(1)
        self._value = make_label(value, "Value")
        self._value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        # Long sysfs paths must not force the card wider than the window.
        self._value.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._value.setMinimumWidth(0)
        layout.addWidget(self._value, 0)

    def set_value(self, value: str) -> None:
        display = value if value else "—"
        self._value.setText(display)
        self._value.setToolTip(display)


class MetricTile(QFrame):
    """Compact KPI tile used by the dashboard."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        detail: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CardMuted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        layout.addWidget(section_title(caption))
        self._value = make_label(value, "BigValue")
        layout.addWidget(self._value)
        self._detail = muted(detail, wrap=True)
        layout.addWidget(self._detail)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_detail(self, detail: str) -> None:
        self._detail.setText(detail)
        self._detail.setToolTip(detail)


class ActionButton(QPushButton):
    """Small helper for consistent button variants."""

    def __init__(
        self,
        text: str,
        *,
        variant: str = "ghost",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        if variant == "primary":
            self.setObjectName("Primary")
        elif variant == "danger":
            self.setObjectName("Danger")
        elif variant == "ghost":
            self.setObjectName("Ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)


def sum_lit(colors: Iterable[RGB | None]) -> int:
    """Count illuminated segments in a frame (used in tests and captions)."""
    return sum(1 for color in colors if color is not None)
