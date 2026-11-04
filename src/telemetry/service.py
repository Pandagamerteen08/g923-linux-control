"""Telemetry orchestration: hook polling, staleness detection, fallback.

The service is the only owner of the active :class:`HookPoller`.  It ticks at
30 Hz, decides whether the LEDs should follow game telemetry or the physical
throttle pedal, and emits a single ``ratio_changed`` signal for the LED loop
and the UI preview.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..config import AppSettings
from .fallback import PedalFallback
from .hooks import (
    HookCatalog,
    HookPoller,
    HookSpec,
    TelemetrySample,
    discover_hooks,
)

log = logging.getLogger(__name__)

SOURCE_TELEMETRY = "telemetry"
SOURCE_PEDAL = "pedal"
SOURCE_IDLE = "idle"

_TICK_MS = 33  # ~30 Hz: matches the LED update rate


class TelemetryService(QObject):
    """Drive the LED ratio from a hook feed or the throttle pedal.

    Signals:
        ratio_changed(float, str): Ratio (0–1) and its source
            (``telemetry``/``pedal``/``idle``).
        sample_received(object): Latest :class:`TelemetrySample`.
        hooks_changed(object): Updated :class:`HookCatalog`.
        status_changed(str): One-line status suitable for the UI.
        hook_error(str): Latest hook problem, emitted only when it changes.
    """

    ratio_changed = pyqtSignal(float, str)
    sample_received = pyqtSignal(object)
    hooks_changed = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    hook_error = pyqtSignal(str)

    def __init__(self, settings: AppSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._catalog = HookCatalog()
        self._poller: HookPoller | None = None
        self._active_hook_id = settings.telemetry.active_hook
        self._active_spec: HookSpec | None = None
        self._last_sample: TelemetrySample | None = None
        self._last_sample_at = 0.0
        self._last_error = ""
        self._throttle = 0.0
        self._fallback = PedalFallback(deadzone=settings.telemetry.throttle_deadzone)
        self._ratio = 0.0
        self._source = SOURCE_IDLE
        self._status = "Idle · no telemetry"
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

    # -- state ------------------------------------------------------------
    @property
    def catalog(self) -> HookCatalog:
        return self._catalog

    @property
    def active_hook_id(self) -> str:
        return self._active_hook_id

    @property
    def active_spec(self) -> HookSpec | None:
        return self._active_spec

    @property
    def sample(self) -> TelemetrySample | None:
        return self._last_sample

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def source(self) -> str:
        return self._source

    @property
    def status_text(self) -> str:
        return self._status

    @property
    def last_hook_error(self) -> str:
        """Most recent hook error, or an empty string when healthy."""
        return self._last_error

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Scan hooks, restore the saved selection and start ticking."""
        self.refresh_hooks()
        if self._active_hook_id:
            spec = self._catalog.find(self._active_hook_id)
            if spec is not None:
                self._start_poller(spec)
            else:
                self._active_hook_id = ""
                self._set_status("Saved telemetry hook was not found")
        if not self._timer.isActive():
            self._timer.start()

    def shutdown(self) -> None:
        """Stop polling and release the worker thread."""
        self._timer.stop()
        self._stop_poller()
        self._fallback.reset()

    def configure(self, settings: AppSettings) -> None:
        """Adopt new settings, restarting the poller when its cadence changes."""
        previous = self._settings
        self._settings = settings
        self._fallback = PedalFallback(
            deadzone=settings.telemetry.throttle_deadzone,
            smoothing=self._fallback.smoothing,
        )
        if self._active_spec is not None and (
            previous.telemetry.poll_interval_ms
            != settings.telemetry.poll_interval_ms
        ):
            self._start_poller(self._active_spec)

    # -- hooks ------------------------------------------------------------
    def refresh_hooks(self) -> HookCatalog:
        """Rescan hook directories and publish the catalogue."""
        catalog = discover_hooks()
        self._catalog = catalog
        self.hooks_changed.emit(catalog)
        for warning in catalog.warnings:
            log.warning("Hook scan: %s", warning)
        return catalog

    def set_active_hook(self, hook_id: str) -> None:
        """Select a hook by ID, or ``""`` to disable telemetry polling."""
        hook_id = hook_id or ""
        if hook_id == self._active_hook_id and self._poller is not None:
            return
        self._active_hook_id = hook_id
        self._stop_poller()
        self._last_sample = None
        self._last_sample_at = 0.0
        self._last_error = ""
        if not hook_id:
            self._set_status("Telemetry hook disabled")
            return
        spec = self._catalog.find(hook_id)
        if spec is None:
            self._set_status("Selected telemetry hook is unavailable")
            return
        self._start_poller(spec)

    def _start_poller(self, spec: HookSpec) -> None:
        self._stop_poller()
        self._active_spec = spec
        interval = (
            self._settings.telemetry.poll_interval_ms
            if self._settings.telemetry.poll_interval_ms
            else spec.poll_interval_ms
        )
        poller = HookPoller(
            spec,
            interval_ms=interval,
            default_max_rpm=self._settings.telemetry.max_rpm,
        )
        poller.sample.connect(self._on_sample)
        poller.error.connect(self._on_hook_error)
        self._poller = poller
        poller.start()
        self._set_status(f"Waiting for telemetry · {spec.name}")
        log.info("Started telemetry hook %s (%s)", spec.name, spec.kind)

    def _stop_poller(self) -> None:
        poller, self._poller = self._poller, None
        self._active_spec = None
        if poller is not None:
            try:
                poller.sample.disconnect(self._on_sample)
                poller.error.disconnect(self._on_hook_error)
            except TypeError:
                pass
            poller.stop()

    def _on_sample(self, sample: TelemetrySample) -> None:
        self._last_sample = sample
        self._last_sample_at = time.monotonic()
        self._last_error = ""
        self.sample_received.emit(sample)

    def _on_hook_error(self, message: str) -> None:
        self._last_error = message
        self.hook_error.emit(message)
        name = self._active_spec.name if self._active_spec else "Telemetry hook"
        if self._source != SOURCE_TELEMETRY:
            self._set_status(f"{name}: {message}")

    # -- pedal input & tick ----------------------------------------------
    def set_pedal_input(self, throttle: float) -> None:
        """Feed normalized throttle travel from the wheel reader."""
        self._throttle = max(0.0, min(1.0, float(throttle)))

    def _telemetry_is_live(self, now: float) -> bool:
        if self._last_sample is None or self._last_sample_at <= 0:
            return False
        age_ms = (now - self._last_sample_at) * 1000.0
        return age_ms <= self._settings.telemetry.stale_timeout_ms

    def _tick(self) -> None:
        now = time.monotonic()
        ratio = 0.0
        source = SOURCE_IDLE

        if self._telemetry_is_live(now):
            sample = self._last_sample
            candidate = None
            if sample is not None:
                candidate = sample.ratio
                if candidate is None and sample.throttle is not None:
                    candidate = sample.throttle
            if candidate is not None:
                ratio = max(0.0, min(1.0, candidate))
                source = SOURCE_TELEMETRY
        elif self._settings.leds.fallback_enabled:
            ratio = self._fallback.map(self._throttle)
            source = SOURCE_PEDAL

        self._update_status(source, ratio)
        if (
            source != self._source
            or abs(ratio - self._ratio) >= 0.002
        ):
            self._source = source
            self._ratio = ratio
            self.ratio_changed.emit(ratio, source)

    def _update_status(self, source: str, ratio: float) -> None:
        sample = self._last_sample
        if source == SOURCE_TELEMETRY and sample is not None:
            name = self._active_spec.name if self._active_spec else "Telemetry"
            status = f"{name} · {sample.summary}"
        elif source == SOURCE_PEDAL:
            if self._last_error and self._active_hook_id:
                status = (
                    f"Fallback active · throttle {self._throttle * 100:.0f}% · "
                    f"{self._last_error}"
                )
            else:
                status = f"Fallback active · throttle {self._throttle * 100:.0f}%"
        elif self._settings.leds.fallback_enabled:
            status = "Idle · no telemetry; press the throttle to drive the LEDs"
        else:
            status = "Idle · no telemetry and fallback disabled"
        if status != self._status:
            self._set_status(status)

    def _set_status(self, status: str) -> None:
        self._status = status
        self.status_changed.emit(status)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def hook_source_label(spec: HookSpec | None) -> str:
        if spec is None:
            return "No hook selected"
        if spec.source_type == "file":
            return f"{spec.name} · file"
        if spec.source_type == "command":
            return f"{spec.name} · command"
        return f"{spec.name} · Python"

    def reload_hooks_and_keep_selection(self) -> None:
        """Rescan hook files, reconnecting the active hook if it still exists."""
        previous = self._active_hook_id
        self.refresh_hooks()
        if previous and self._catalog.find(previous):
            self._active_hook_id = ""
            self.set_active_hook(previous)
        else:
            self._stop_poller()

    @staticmethod
    def user_hook_dir() -> Path:
        from ..config import default_config_dir

        return default_config_dir() / "hooks"
