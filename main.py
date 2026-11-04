#!/usr/bin/env python3
"""G923 Linux Control — application entry point.

Run from the repository root::

    python main.py

The process is a single foreground GUI.  It installs signal handlers for
``SIGINT``/``SIGTERM``, keeps a lightweight timer alive so Python can process
signals while Qt's event loop runs, and performs one idempotent shutdown that
releases evdev/hidraw handles and writes the settings file.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from src.app import ApplicationContext
from src.config import SettingsManager
from src.constants import APP_ID, APP_NAME, APP_VERSION, PROJECT_URL
from src.gui.icons import app_icon
from src.gui.main_window import MainWindow
from src.gui.theme import apply_theme
from src.gui.tray import TrayController

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        prog="g923-linux-control",
        description=f"{APP_NAME} — offline wheel control panel for Linux.",
        epilog=f"Project home: {PROJECT_URL}",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug logging on stderr",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="do not create a system-tray icon",
    )
    parser.add_argument(
        "--reset-settings",
        action="store_true",
        help="rewrite settings.json with defaults before starting",
    )
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    """Configure stderr-only logging; the application writes no log files."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def install_signal_handlers(app: QApplication) -> QTimer:
    """Quit cleanly on Ctrl+C/SIGTERM.

    Qt's event loop does not run Python bytecode while idle, so a no-op timer
    wakes the interpreter periodically and lets signal handlers execute.
    """
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: app.quit())

    heartbeat = QTimer()
    heartbeat.setInterval(250)
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start()
    return heartbeat


def main(argv: list[str] | None = None) -> int:
    """Start the GUI and block until the user quits."""
    args = parse_args(argv)
    configure_logging(args.verbose)

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    apply_theme(app)

    manager = SettingsManager()
    if args.reset_settings:
        manager.reset()
        print(f"Settings reset: {manager.path}")

    settings = manager.load()
    context = ApplicationContext(manager, settings)
    window = MainWindow(context)

    tray: TrayController | None = None
    if not args.no_tray and QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayController(app_icon(), window)
        tray.show_requested.connect(window.show_and_raise)
        tray.quit_requested.connect(window.request_quit)
        tray.clear_leds_requested.connect(context.clear_leds)
        context.wheel.connection_changed.connect(tray.set_connected)
        window.set_tray_available(tray.available)
        # Hiding to the tray must not terminate the process.
        app.setQuitOnLastWindowClosed(not tray.available)
    else:
        window.set_tray_available(False)

    _heartbeat = install_signal_handlers(app)
    app.aboutToQuit.connect(context.shutdown)

    context.start()
    if settings.ui.start_minimized and tray is not None and tray.available:
        log.info("Starting minimized in the system tray")
    else:
        window.show()

    try:
        exit_code = app.exec()
    finally:
        context.shutdown()
        if tray is not None:
            tray.hide()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
