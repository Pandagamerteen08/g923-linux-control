"""Main window: header, sidebar navigation and service wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_NAME, APP_VERSION
from ..hardware.device import DeviceInfo
from ..hardware.sysfs import ApplyReport, DriverSnapshot
from ..telemetry.hooks import HookCatalog
from ..telemetry.led_engine import LedFrame
from .dashboard import DashboardPage
from .leds import LedsPage
from .pedals import PedalsPage
from .steering import SteeringPage
from .widgets import StatusBadge, make_label, muted, section_title

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from ..app import ApplicationContext

_PAGE_NAMES = ("dashboard", "steering", "pedals", "leds")
_PAGE_LABELS = (
    "Dashboard",
    "Steering & Force Feedback",
    "Pedals & Inputs",
    "Rev LEDs & Hooks",
)


class MainWindow(QMainWindow):
    """Top-level dashboard window."""

    def __init__(self, context: "ApplicationContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._tray_available = False
        self._force_close = False

        settings = context.settings
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1020, 700)
        self.resize(settings.ui.window_width, settings.ui.window_height)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        self._dashboard_page = DashboardPage()
        self._steering_page = SteeringPage()
        self._pedals_page = PedalsPage()
        self._leds_page = LedsPage()
        self._pages = (
            self._dashboard_page,
            self._steering_page,
            self._pedals_page,
            self._leds_page,
        )
        for page in self._pages:
            self._stack.addWidget(self._wrap_page(page))
        body.addWidget(self._stack, 1)
        outer.addLayout(body, 1)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready — scanning for the wheel", 6000)

        self._connect_services()
        self._load_initial_state()

        try:
            index = _PAGE_NAMES.index(settings.ui.last_page)
        except ValueError:
            index = 0
        self.navigate(index)

    # -- layout -----------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(86)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(14)

        mark = make_label("G9", "AppMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(make_label(APP_NAME, "Title"))
        titles.addWidget(make_label("Offline wheel control for Linux", "Subtitle"))
        layout.addLayout(titles)
        layout.addStretch(1)

        self._badge = StatusBadge()
        self._badge.set_status(None, "Scanning")
        layout.addWidget(self._badge)
        layout.addWidget(self._vertical_divider())

        firmware_block = QVBoxLayout()
        firmware_block.setSpacing(3)
        firmware_block.addWidget(section_title("Firmware"))
        self._firmware_value = make_label("—", "Value")
        self._firmware_value.setMinimumWidth(150)
        firmware_block.addWidget(self._firmware_value)
        layout.addLayout(firmware_block)
        layout.addWidget(self._vertical_divider())

        profile_block = QVBoxLayout()
        profile_block.setSpacing(3)
        profile_block.addWidget(section_title("Profile"))
        self._profile_value = make_label(self._context.settings.profile, "Value")
        profile_block.addWidget(self._profile_value)
        layout.addLayout(profile_block)
        return header

    @staticmethod
    def _vertical_divider() -> QFrame:
        line = QFrame()
        line.setFixedSize(1, 34)
        line.setStyleSheet("background-color: #2c3037;")
        return line

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 20, 14, 16)
        layout.setSpacing(6)

        layout.addWidget(make_label("Navigation", "SidebarCaption"))
        layout.addSpacing(4)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        for index, label in enumerate(_PAGE_LABELS):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, target=index: self.navigate(target)
            )
            self._nav_group.addButton(button, index)
            layout.addWidget(button)
            self._nav_buttons.append(button)

        layout.addStretch(1)
        layout.addWidget(make_label("Local only", "SidebarCaption"))
        for line in (
            "No background daemons",
            "No accounts or telemetry uploads",
            "Settings in one local JSON file",
        ):
            label = muted(line, wrap=False)
            label.setStyleSheet("font-size: 11px; color: #7d838f;")
            layout.addWidget(label)

        layout.addSpacing(10)
        footer = make_label(f"v{APP_VERSION} · MIT licensed", "FooterNote")
        layout.addWidget(footer)
        return sidebar

    @staticmethod
    def _wrap_page(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(0)
        layout.addWidget(page, 1)
        scroll.setWidget(container)
        return scroll

    # -- wiring -----------------------------------------------------------
    def _connect_services(self) -> None:
        wheel = self._context.wheel
        wheel.connection_changed.connect(self._on_connection)
        wheel.device_changed.connect(self._on_device)
        wheel.firmware_changed.connect(self._on_firmware)
        wheel.driver_changed.connect(self._on_driver)
        wheel.axis_changed.connect(self._on_axis)
        wheel.button_changed.connect(self._on_button)
        wheel.apply_finished.connect(self._on_apply_finished)
        wheel.led_status_changed.connect(self._on_led_status)
        wheel.notice.connect(self._on_notice)

        telemetry = self._context.telemetry
        telemetry.status_changed.connect(self._on_telemetry_status)
        telemetry.hooks_changed.connect(self._on_hooks_changed)
        telemetry.hook_error.connect(self._on_hook_error)

        self._context.led_controller.frame_ready.connect(self._on_led_frame)

        self._steering_page.steering_changed.connect(self._on_steering_changed)
        self._steering_page.reapply_requested.connect(self._on_reapply)
        self._steering_page.export_requested.connect(self._on_export_preset)
        self._leds_page.leds_changed.connect(self._on_leds_changed)
        self._leds_page.hook_changed.connect(self._on_hook_changed)
        self._leds_page.refresh_hooks_requested.connect(self._on_refresh_hooks)

    def _load_initial_state(self) -> None:
        settings = self._context.settings
        self._dashboard_page.update_profile(settings)
        self._steering_page.load(settings.steering)
        self._pedals_page.set_rotation(settings.steering.rotation_deg)
        self._steering_page.set_connected(self._context.wheel.connected)
        self._steering_page.set_oversteer_status(
            self._context.oversteer_status().summary
        )
        self._leds_page.load(
            settings.leds,
            self._context.telemetry.catalog,
            settings.telemetry.active_hook,
        )
        self._dashboard_page.update_telemetry(
            self._context.telemetry.status_text,
            self._context.telemetry.source,
        )
        self._dashboard_page.set_hook_name(
            self._context.telemetry.active_spec.name
            if self._context.telemetry.active_spec
            else "None"
        )
        self._on_led_status(self._context.wheel.led_status)

    # -- navigation -------------------------------------------------------
    def navigate(self, index: int) -> None:
        if not 0 <= index < len(self._pages):
            return
        self._stack.setCurrentIndex(index)
        self._nav_buttons[index].setChecked(True)
        self._context.settings.ui.last_page = _PAGE_NAMES[index]
        self._context.schedule_save()

    def show_and_raise(self) -> None:
        """Show the window from the tray and bring it to the front."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def set_tray_available(self, available: bool) -> None:
        self._tray_available = available

    # -- wheel slots ------------------------------------------------------
    def _on_connection(self, connected: bool) -> None:
        self._dashboard_page.update_connection(connected)
        self._steering_page.set_connected(connected)
        self._badge.set_status(
            connected, "Detected" if connected else "Disconnected"
        )
        if not connected:
            self._pedals_page.reset_inputs()
            self.statusBar().showMessage("Wheel disconnected", 5000)

    def _on_device(self, info: DeviceInfo | None) -> None:
        self._dashboard_page.update_device(info)
        if info is None:
            self._profile_value.setText(self._context.settings.profile)
            return
        self._profile_value.setText(self._context.settings.profile)
        self._pedals_page.set_rotation(self._context.settings.steering.rotation_deg)

    def _on_firmware(self, text: str) -> None:
        self._dashboard_page.update_firmware(text)
        self._firmware_value.setText(text)
        self._firmware_value.setToolTip(text)

    def _on_driver(self, snapshot: DriverSnapshot) -> None:
        self._dashboard_page.update_driver(snapshot)
        self._steering_page.update_driver(snapshot)

    def _on_axis(self, name: str, value: float) -> None:
        self._dashboard_page.update_axis(name, value)
        self._pedals_page.update_axis(name, value)

    def _on_button(self, name: str, pressed: bool) -> None:
        self._pedals_page.update_button(name, pressed)

    def _on_apply_finished(self, report: ApplyReport) -> None:
        self._dashboard_page.update_apply_report(report)
        self._steering_page.set_report(report)

    def _on_led_status(self, text: str) -> None:
        self._dashboard_page.update_led_status(text)
        self._leds_page.set_led_status(text)

    def _on_led_frame(self, frame: LedFrame) -> None:
        self._leds_page.set_live_frame(frame)
        self._pedals_page.set_leds(frame.colors)

    def _on_notice(self, severity: str, message: str) -> None:
        timeout = 12000 if severity in {"error", "warning"} else 7000
        prefix = {"error": "Error", "warning": "Warning"}.get(severity, "Info")
        self.statusBar().showMessage(f"{prefix}: {message}", timeout)

    # -- telemetry slots --------------------------------------------------
    def _on_telemetry_status(self, status: str) -> None:
        source = self._context.telemetry.source
        self._dashboard_page.update_telemetry(status, source)
        self._leds_page.set_status(status, source)

    def _on_hooks_changed(self, catalog: HookCatalog) -> None:
        active_id = self._context.telemetry.active_hook_id
        self._leds_page.set_catalog(catalog, active_id)
        spec = catalog.find(active_id)
        self._dashboard_page.set_hook_name(spec.name if spec else "None")
        if catalog.warnings:
            self._leds_page.set_hook_error("; ".join(catalog.warnings[:2]))

    def _on_hook_error(self, message: str) -> None:
        self._leds_page.set_hook_error(message)

    # -- page actions -----------------------------------------------------
    def _on_steering_changed(self, steering) -> None:  # type: ignore[no-untyped-def]
        self._context.update_steering(steering)
        self._pedals_page.set_rotation(steering.rotation_deg)
        self._dashboard_page.update_profile(self._context.settings)

    def _on_reapply(self) -> None:
        self._context.reapply_steering()

    def _on_export_preset(self) -> None:
        try:
            path = self._context.export_oversteer()
        except OSError as exc:
            QMessageBox.warning(
                self, "Export failed", f"Could not write the preset:\n{exc}"
            )
            return
        self.statusBar().showMessage(f"Oversteer preset written to {path}", 10000)
        self._steering_page.set_oversteer_status(
            self._context.oversteer_status().summary
        )
        QMessageBox.information(
            self,
            "Oversteer preset exported",
            f"Profile data was written to:\n\n{path}\n\n"
            "Oversteer has no scripting interface; this file records the same "
            "kernel values for reference or manual import.",
        )

    def _on_leds_changed(self, leds) -> None:  # type: ignore[no-untyped-def]
        self._context.update_leds(leds)
        self._dashboard_page.update_profile(self._context.settings)

    def _on_hook_changed(self, hook_id: str) -> None:
        self._context.update_hook(hook_id)
        spec = self._context.telemetry.catalog.find(hook_id)
        self._dashboard_page.set_hook_name(spec.name if spec else "None")

    def _on_refresh_hooks(self) -> None:
        self._context.telemetry.reload_hooks_and_keep_selection()
        catalog = self._context.telemetry.catalog
        self._on_hooks_changed(catalog)
        current = self._context.telemetry.active_hook_id
        if current != self._context.settings.telemetry.active_hook:
            self._context.update_hook(current)
        self.statusBar().showMessage(
            f"Scanned hooks · {len(catalog.hooks)} found"
            + (f" · {len(catalog.warnings)} warning(s)" if catalog.warnings else ""),
            8000,
        )

    # -- window lifecycle -------------------------------------------------
    def _save_ui_state(self) -> None:
        ui = self._context.settings.ui
        ui.window_width = self.width()
        ui.window_height = self.height()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_ui_state()
        settings = self._context.settings
        if (
            not self._force_close
            and self._tray_available
            and settings.ui.close_to_tray
        ):
            self._context.schedule_save()
            self.hide()
            event.ignore()
            return
        self._context.save_now()
        event.accept()

    def request_quit(self) -> None:
        """Quit the application from the tray or a shortcut."""
        self._force_close = True
        self._save_ui_state()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()
