"""Programmatically drawn application icon.

Keeping the icon in code avoids shipping binary assets and guarantees a crisp
icon at every tray/window size.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from ..constants import COLOR_ACCENT


def _render(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.06
    body = QRectF(margin, margin, size - margin * 2, size - margin * 2)
    painter.setPen(QPen(QColor("#343941"), max(1.0, size * 0.012)))
    painter.setBrush(QColor("#1d1f24"))
    painter.drawRoundedRect(body, size * 0.24, size * 0.24)

    # Steering ring.
    center = QPointF(size / 2.0, size / 2.0)
    radius = size * 0.26
    ring = QRectF(
        center.x() - radius, center.y() - radius, radius * 2, radius * 2
    )
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(
        QPen(
            QColor(COLOR_ACCENT),
            max(1.0, size * 0.075),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    painter.drawEllipse(ring)

    # Top marker.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#eef1f6"))
    painter.drawRoundedRect(
        QRectF(center.x() - size * 0.025, center.y() - radius - size * 0.05,
               size * 0.05, size * 0.075),
        size * 0.02,
        size * 0.02,
    )

    # Hub.
    painter.setBrush(QColor("#eef1f6"))
    painter.drawEllipse(center, size * 0.035, size * 0.035)

    # Three spokes.
    painter.setPen(
        QPen(QColor("#8b93a1"), max(1.0, size * 0.025), Qt.PenStyle.SolidLine,
             Qt.PenCapStyle.RoundCap)
    )
    for dx, dy in ((0.0, 1.0), (-0.87, -0.5), (0.87, -0.5)):
        painter.drawLine(
            QPointF(center.x() + dx * size * 0.035, center.y() + dy * size * 0.035),
            QPointF(center.x() + dx * radius, center.y() + dy * radius),
        )

    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Build a multi-resolution icon suitable for the window and tray."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render(size))
    return icon
