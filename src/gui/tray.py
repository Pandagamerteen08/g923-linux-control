"""System-tray integration.

The tray is optional: when the desktop has no StatusNotifier/xembed host the
controller simply reports ``available == False`` and the window keeps normal
close semantics.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from ..constants import APP_NAME, APP_VERSION


class TrayController(QObject):
    """Own the tray icon and its small action menu."""

    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    clear_leds_requested = pyqtSignal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray = QSystemTrayIcon(icon, self)
        menu = QMenu()

        self._status = QAction("Wheel: disconnected", menu)
        self._status.setEnabled(False)
        menu.addAction(self._status)
        menu.addSeparator()

        show_action = QAction("Open dashboard", menu)
        show_action.triggered.connect(self.show_requested.emit)
        menu.addAction(show_action)

        clear_action = QAction("Clear rev LEDs", menu)
        clear_action.triggered.connect(self.clear_leds_requested.emit)
        menu.addAction(clear_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        tray.setToolTip(f"{APP_NAME} {APP_VERSION}")
        tray.activated.connect(self._on_activated)
        tray.show()
        self._tray = tray

    @property
    def available(self) -> bool:
        return self._tray is not None

    def set_connected(self, connected: bool) -> None:
        """Reflect wheel state in the tray menu without extra notifications."""
        status = "Wheel: connected" if connected else "Wheel: disconnected"
        self._status.setText(status)
        if self._tray is not None:
            self._tray.setToolTip(f"{APP_NAME} — {status}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def hide(self) -> None:
        if self._tray is not None:
            self._tray.hide()


__all__ = ["TrayController"]
