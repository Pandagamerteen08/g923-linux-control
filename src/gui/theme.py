"""Dark theme application: palette, fonts and the QSS stylesheet."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from ..constants import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_SURFACE,
    COLOR_SURFACE_ALT,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_WARNING,
)

log = logging.getLogger(__name__)

_FONT_STACK = ("Inter", "Ubuntu", "Noto Sans", "DejaVu Sans", "Sans Serif")


def assets_dir() -> Path:
    """Resolve the assets directory in source and PyInstaller layouts."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return bundle_root / "assets"


def load_stylesheet() -> str:
    """Read ``assets/style.qss``; return an empty string if unavailable."""
    path = assets_dir() / "style.qss"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Could not load stylesheet %s: %s", path, exc)
        return ""


def preferred_font() -> QFont:
    """Pick the first installed font from the design stack."""
    try:
        families = set(QFontDatabase.families())
    except Exception:  # pragma: no cover - platform dependent
        families = set()
    for family in _FONT_STACK:
        if family in families:
            return QFont(family, 10)
    return QFont()


def qcolor(value: str, alpha: int | None = None) -> QColor:
    """Build a :class:`QColor` from a hex token, optionally with alpha."""
    color = QColor(value)
    if alpha is not None:
        color.setAlpha(max(0, min(255, alpha)))
    return color


def build_palette() -> QPalette:
    """Create the dark application palette used by native Qt widgets."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR_SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLOR_SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(COLOR_DANGER))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#07222a"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLOR_TEXT_MUTED))
    palette.setColor(QPalette.ColorRole.Link, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.ColorRole.Mid, QColor(COLOR_BORDER))
    palette.setColor(QPalette.ColorRole.Dark, QColor(COLOR_BG))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#0e0f12"))
    for role, color in (
        (QPalette.ColorRole.WindowText, COLOR_TEXT_MUTED),
        (QPalette.ColorRole.Text, COLOR_TEXT_MUTED),
        (QPalette.ColorRole.ButtonText, COLOR_TEXT_MUTED),
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return palette


def apply_theme(app: QApplication) -> None:
    """Apply the Fusion style, dark palette, font and stylesheet."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setFont(preferred_font())
    app.setStyleSheet(load_stylesheet())


__all__ = [
    "COLOR_ACCENT",
    "COLOR_DANGER",
    "COLOR_SUCCESS",
    "COLOR_WARNING",
    "apply_theme",
    "assets_dir",
    "build_palette",
    "load_stylesheet",
    "preferred_font",
    "qcolor",
]
