"""Rev LEDs and telemetry-hook page."""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import LedBand, LedSettings
from ..telemetry.hooks import HookCatalog
from ..telemetry.led_engine import LedEngine, LedFrame
from ..telemetry.service import TelemetryService
from .widgets import (
    ActionButton,
    Card,
    KeyValueRow,
    LedStrip,
    SliderRow,
    ToggleRow,
    divider,
    make_label,
    muted,
    page_header,
    section_title,
)

_BAND_PALETTE = ("#3ea6ff", "#a78bfa", "#21d4a0", "#f2c94c", "#ff8a3d")


class _BandRow(QWidget):
    """Editor row for a single RPM colour band."""

    changed = pyqtSignal(int, object)
    removed = pyqtSignal(int)

    def __init__(
        self, index: int, band: LedBand, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._color = band.normalized().color
        self._band = band.normalized()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        self._threshold = QSpinBox()
        self._threshold.setRange(0, 100)
        self._threshold.setSuffix("%")
        self._threshold.setValue(self._band.threshold)
        self._threshold.setFixedWidth(88)
        self._threshold.setToolTip("RPM percentage at which this band begins")
        layout.addWidget(self._threshold)
        layout.addWidget(muted("of redline", wrap=False))

        self._swatch = QPushButton()
        self._swatch.setFixedSize(38, 26)
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.setToolTip("Choose the band colour")
        self._paint_swatch()
        layout.addWidget(self._swatch)

        self._flash = QCheckBox("Flash")
        self._flash.setChecked(self._band.flash)
        self._flash.setToolTip("Blink the illuminated bar while this band is active")
        layout.addWidget(self._flash)

        layout.addStretch(1)

        self._lit_hint = muted("", wrap=False)
        layout.addWidget(self._lit_hint)

        remove = QPushButton("Remove")
        remove.setObjectName("Ghost")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Remove this band (at least one band is kept)")
        remove.clicked.connect(lambda: self.removed.emit(self._index))
        layout.addWidget(remove)

        self._threshold.valueChanged.connect(self._emit_change)
        self._flash.toggled.connect(self._emit_change)
        self._swatch.clicked.connect(self._pick_color)

    def _paint_swatch(self) -> None:
        self._swatch.setStyleSheet(
            "QPushButton {"
            f"background-color: {self._color};"
            "border: 1px solid #3a4048;"
            "border-radius: 7px;"
            "}"
            "QPushButton:hover { border-color: #eef1f6; }"
        )

    def _pick_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(self._color), self, "Select band colour"
        )
        if not selected.isValid():
            return
        self._color = selected.name()
        self._paint_swatch()
        self._emit_change()

    def _emit_change(self, *_args) -> None:
        self._band = LedBand(
            threshold=self._threshold.value(),
            color=self._color,
            flash=self._flash.isChecked(),
        )
        self.changed.emit(self._index, self._band)

    def set_lit_hint(self, text: str) -> None:
        self._lit_hint.setText(text)


class LedsPage(QWidget):
    """Shift-light customisation, telemetry selection and hardware status."""

    leds_changed = pyqtSignal(object)
    hook_changed = pyqtSignal(str)
    refresh_hooks_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._settings = LedSettings()
        self._bands: list[LedBand] = list(self._settings.bands)
        self._catalog = HookCatalog()
        self._preview_frame: LedFrame | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(
            page_header(
                "Rev LEDs & Telemetry Hooks",
                "Shape the shift-light response, then feed it from a game hook or "
                "the throttle pedal when a game provides no telemetry.",
            )
        )

        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(self._build_preview_card(), 1)
        top.addWidget(self._build_telemetry_card(), 1)
        root.addLayout(top)

        root.addWidget(self._build_bands_card(), 1)
        root.addWidget(self._build_hardware_card())

    # -- construction -----------------------------------------------------
    def _build_preview_card(self) -> Card:
        card = Card(
            "Shift-light output",
            "Live frame currently sent to the wheel",
            accent=True,
        )
        self._live_strip = LedStrip(self._settings.led_count, height=48)
        card.add_widget(self._live_strip)

        info = QHBoxLayout()
        info.addWidget(section_title("FRAME"), 0)
        info.addStretch(1)
        self._lit_label = make_label("0 lit", "AccentValue")
        info.addWidget(self._lit_label, 0)
        card.add_layout(info)

        self._source_row = KeyValueRow("Frame source", "Idle")
        card.add_widget(self._source_row)
        self._brightness = SliderRow(
            "Brightness",
            0,
            100,
            self._settings.brightness,
            suffix="%",
            description=(
                "Scales the preview colours and the emulated LED brightness. "
                "The wheel's monochrome bar is driven as a bitmask."
            ),
        )
        self._brightness.valueChanged.connect(self._on_brightness)
        card.add_widget(self._brightness)
        return card

    def _build_telemetry_card(self) -> Card:
        card = Card("Telemetry feed", "Drop-in hooks for games without native LEDs")
        self._hook_combo = QComboBox()
        self._hook_combo.setMinimumWidth(240)
        self._hook_combo.setToolTip(
            "Hooks are loaded from the project hooks/ folder and "
            "~/.config/g923-linux-control/hooks/."
        )
        self._hook_combo.currentIndexChanged.connect(self._on_hook_selected)
        card.add_widget(self._hook_combo)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        rescan = ActionButton("Rescan hooks")
        rescan.clicked.connect(self.refresh_hooks_requested.emit)
        open_folder = ActionButton("Open hooks folder")
        open_folder.clicked.connect(self._open_hooks_folder)
        actions.addWidget(rescan)
        actions.addWidget(open_folder)
        card.add_layout(actions)

        self._fallback = ToggleRow(
            "Pedal fallback",
            "When telemetry is absent or stale, map throttle travel to the rev bar.",
            checked=self._settings.fallback_enabled,
        )
        self._fallback.toggled.connect(self._on_fallback)
        card.add_widget(self._fallback)

        card.add_widget(divider())
        self._feed_status = KeyValueRow("Feed", "Idle")
        card.add_widget(self._feed_status)
        self._scan_label = make_label("", "MutedSmall", word_wrap=True)
        self._scan_label.hide()
        card.add_widget(self._scan_label)
        self._error_label = make_label("", "ErrorText", word_wrap=True)
        self._error_label.hide()
        card.add_widget(self._error_label)
        return card

    def _build_bands_card(self) -> Card:
        card = Card(
            "RPM colour bands",
            "Green → yellow → red → flashing blue, tuned to your shift points",
        )
        header_action = QPushButton("Add band")
        header_action.setObjectName("Ghost")
        header_action.setCursor(Qt.CursorShape.PointingHandCursor)
        header_action.clicked.connect(self._add_band)
        card.add_header_action(header_action)

        self._band_strip = LedStrip(self._settings.led_count, height=34)
        card.add_widget(self._band_strip)

        self._preview_slider = SliderRow(
            "Preview at",
            0,
            100,
            78,
            suffix="%",
            description="Scratch the bar without waiting for a game feed.",
        )
        self._preview_slider.valueChanged.connect(self._refresh_preview)
        card.add_widget(self._preview_slider)

        card.add_widget(divider())
        self._bands_layout = QVBoxLayout()
        self._bands_layout.setSpacing(6)
        card.add_layout(self._bands_layout)

        hint = muted(
            "Bands are cumulative: the active colour applies to the whole "
            "illuminated bar. Flashing bands toggle the bar at the configured rate."
        )
        card.add_widget(hint)
        return card

    def _build_hardware_card(self) -> Card:
        card = Card("Hardware output", "Writes are best-effort and never block the UI")
        self._led_status = muted("Checking LED output…")
        card.add_widget(self._led_status)
        card.add_widget(divider())
        card.add_widget(
            muted(
                "The wheel's rev bar is monochrome and addressed with a bitmask. "
                "Colour bands and brightness are rendered in the preview; flashing "
                "is transmitted by toggling the bitmask. If writes fail, add the "
                "udev rule from the README so your user can open /dev/hidraw*."
            )
        )
        return card

    # -- loading ----------------------------------------------------------
    def load(
        self,
        settings: LedSettings,
        catalog: HookCatalog,
        active_hook_id: str,
    ) -> None:
        """Populate the page from persisted settings and the hook catalogue."""
        self._loading = True
        try:
            self._settings = settings.normalized()
            self._bands = [
                LedBand(
                    threshold=band.threshold,
                    color=band.color,
                    flash=band.flash,
                )
                for band in self._settings.bands
            ]
            self._brightness.set_value(self._settings.brightness)
            self._fallback.setChecked(self._settings.fallback_enabled)
            self._live_strip.set_count(self._settings.led_count)
            self._band_strip.set_count(self._settings.led_count)
            self._rebuild_bands()
            self.set_catalog(catalog, active_hook_id)
        finally:
            self._loading = False
        self._refresh_preview()

    def set_catalog(self, catalog: HookCatalog, active_hook_id: str) -> None:
        """Refresh the hook picker without emitting a selection change."""
        self._catalog = catalog
        self._loading = True
        try:
            self._hook_combo.clear()
            self._hook_combo.addItem("No telemetry hook (fallback only)", "")
            for spec in catalog.hooks:
                label = f"{spec.name}  ·  {spec.kind_label}"
                self._hook_combo.addItem(label, spec.id)
                index = self._hook_combo.count() - 1
                tip = spec.description or spec.source_label
                self._hook_combo.setItemData(index, tip, Qt.ItemDataRole.ToolTipRole)
            target = self._hook_combo.findData(active_hook_id)
            self._hook_combo.setCurrentIndex(target if target >= 0 else 0)
        finally:
            self._loading = False

        if catalog.warnings:
            self._scan_label.setText(
                "Hook scan warnings: " + " · ".join(catalog.warnings[:3])
            )
            self._scan_label.show()
        else:
            self._scan_label.hide()

    # -- external updates -------------------------------------------------
    def set_live_frame(self, frame: LedFrame) -> None:
        self._preview_frame = frame
        self._live_strip.set_colors(frame.colors)
        self._lit_label.setText(f"{frame.lit} lit")

    def set_status(self, status: str, source: str = "") -> None:
        self._feed_status.set_value(status)
        labels = {
            "telemetry": "Game telemetry",
            "pedal": "Throttle fallback",
            "idle": "Idle",
        }
        self._source_row.set_value(labels.get(source, "Idle"))

    def set_led_status(self, text: str) -> None:
        self._led_status.setText(text)
        self._led_status.setToolTip(text)

    def set_hook_error(self, message: str) -> None:
        if message:
            self._error_label.setText(message)
            self._error_label.show()
        else:
            self._error_label.hide()

    # -- band editing -----------------------------------------------------
    def _rebuild_bands(self) -> None:
        while self._bands_layout.count():
            item = self._bands_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, band in enumerate(self._bands):
            row = _BandRow(index, band)
            row.changed.connect(self._on_band_changed)
            row.removed.connect(self._on_band_removed)
            self._bands_layout.addWidget(row)

    def _on_band_changed(self, index: int, band: LedBand) -> None:
        if self._loading or index < 0 or index >= len(self._bands):
            return
        self._bands[index] = band
        self._emit_settings()

    def _on_band_removed(self, index: int) -> None:
        if self._loading or len(self._bands) <= 1:
            return
        if 0 <= index < len(self._bands):
            self._bands.pop(index)
            self._rebuild_bands()
            self._emit_settings()

    def _add_band(self) -> None:
        last_threshold = self._bands[-1].threshold if self._bands else 0
        threshold = min(99, last_threshold + 7)
        color = _BAND_PALETTE[len(self._bands) % len(_BAND_PALETTE)]
        self._bands.append(LedBand(threshold=threshold, color=color, flash=False))
        self._rebuild_bands()
        self._emit_settings()

    def _on_brightness(self, _value: int) -> None:
        if self._loading:
            return
        self._emit_settings()

    def _on_fallback(self, _checked: bool) -> None:
        if self._loading:
            return
        self._emit_settings()

    def _on_hook_selected(self, _index: int) -> None:
        if self._loading:
            return
        hook_id = self._hook_combo.currentData() or ""
        spec = self._catalog.find(hook_id)
        self._feed_status.set_value(
            TelemetryService.hook_source_label(spec)
            if spec is not None
            else "Fallback only"
        )
        self.hook_changed.emit(hook_id)

    def _emit_settings(self) -> None:
        if self._loading:
            return
        self._settings = LedSettings(
            brightness=self._brightness.value(),
            bands=[band.normalized() for band in self._bands],
            fallback_enabled=self._fallback.isChecked(),
            blink_hz=self._settings.blink_hz,
            update_hz=self._settings.update_hz,
            led_count=self._settings.led_count,
        ).normalized()
        self.leds_changed.emit(self._settings)
        self._refresh_preview()

    def _refresh_preview(self, *_args) -> None:
        if not hasattr(self, "_band_strip"):
            return
        engine = LedEngine(
            self._bands or self._settings.bands,
            brightness=self._brightness.value(),
            count=self._settings.led_count,
            blink_hz=self._settings.blink_hz,
        )
        frame = engine.frame(self._preview_slider.value() / 100.0, time.monotonic())
        self._band_strip.set_colors(frame.colors)
        self._preview_slider.setToolTip(
            f"{frame.lit} of {len(frame.colors)} segments illuminated"
        )

    # -- helpers ----------------------------------------------------------
    def _open_hooks_folder(self) -> None:
        directory = TelemetryService.user_hook_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            directory = Path.home()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))


__all__ = ["LedsPage"]
