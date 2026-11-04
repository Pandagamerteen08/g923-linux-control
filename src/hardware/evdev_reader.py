"""Background evdev reader with automatic pedal normalisation.

The reader runs in a :class:`QThread`, polls the character device with a short
``select`` timeout and emits Qt signals that are safe to consume from the GUI
thread.  Pedal axes are self-calibrating: the rest position is sampled when the
node is opened, which handles both pedal polarities found across firmware
revisions without asking the user to configure anything.
"""

from __future__ import annotations

import logging
import select
from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from ..constants import (
    ABS_X,
    AXIS_MAP,
    CODE_TO_BUTTON,
    HAT_MAP,
)

log = logging.getLogger(__name__)

try:  # pragma: no cover - import guard only
    import evdev
    from evdev import InputDevice

    EVDEV_AVAILABLE = True
except ImportError:  # pragma: no cover
    evdev = None  # type: ignore[assignment]
    InputDevice = None  # type: ignore[assignment]
    EVDEV_AVAILABLE = False


@dataclass(slots=True)
class _AxisCalibration:
    """Rest position and travel direction for one analogue channel."""

    rest: int
    minimum: int
    maximum: int
    inverted: bool

    @classmethod
    def from_absinfo(cls, value: int, minimum: int, maximum: int) -> "_AxisCalibration":
        # A pedal at rest sits at one end of its travel.  Whichever end is
        # closer is treated as "released"; pressing moves toward the other.
        inverted = (maximum - value) < (value - minimum)
        return cls(rest=value, minimum=minimum, maximum=maximum, inverted=inverted)

    def normalize(self, value: int, deadzone: float) -> float:
        """Map a raw value to 0.0–1.0 travel, applying a small deadzone."""
        travel = (self.rest - self.minimum) if self.inverted else (self.maximum - self.rest)
        if travel <= 0:
            span = max(1, self.maximum - self.minimum)
            travel = span
        delta = (self.rest - value) if self.inverted else (value - self.rest)
        normalized = max(0.0, min(1.0, delta / travel))
        if deadzone > 0.0 and normalized < deadzone:
            return 0.0
        return normalized


class EvdevReader(QThread):
    """Stream wheel input events as normalized Qt signals.

    Signals:
        axis_changed: ``(logical_name, value, raw_value)``.  Steering is
            reported in ``-1.0..1.0``; pedals in ``0.0..1.0``.
        button_changed: ``(logical_name, pressed)`` for buttons and D-pad.
        disconnected: Emitted once if the device disappears or errors out.
        ready: Emitted once the node is open and calibrated.
    """

    axis_changed = pyqtSignal(str, float, int)
    button_changed = pyqtSignal(str, bool)
    disconnected = pyqtSignal(str)
    ready = pyqtSignal(str)

    _POLL_TIMEOUT_S = 0.1
    _AXIS_EPSILON = 0.0005

    def __init__(
        self,
        event_path: str,
        deadzone: float = 0.02,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._event_path = event_path
        self._deadzone = max(0.0, min(0.5, float(deadzone)))
        self._steering_absinfo: dict[int, object] = {}
        self._calibrations: dict[int, _AxisCalibration] = {}
        self._last_axis_values: dict[str, float] = {}
        self._hat_state: tuple[int, int] = (0, 0)
        self._held_buttons: set[str] = set()

    # -- thread body ------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread entry point
        if not EVDEV_AVAILABLE:
            self.disconnected.emit(
                "python-evdev is not installed; input monitoring is disabled."
            )
            return

        device: "InputDevice | None" = None
        try:
            device = InputDevice(self._event_path)
            self._calibrate(device)
            self.ready.emit(device.name or self._event_path)
            self._loop(device)
        except PermissionError:
            self.disconnected.emit(
                f"Permission denied reading {self._event_path}. "
                "Add your user to the 'input' group or install a udev rule."
            )
        except OSError as exc:
            if not self.isInterruptionRequested():
                log.info("Input device closed: %s", exc)
                self.disconnected.emit(f"Wheel input device closed: {exc}")
        finally:
            if device is not None:
                try:
                    device.close()
                except OSError:
                    pass

    def _calibrate(self, device: "InputDevice") -> None:
        """Cache steering absinfo and sample the rest position of pedals."""
        try:
            self._steering_absinfo = {ABS_X: device.absinfo(ABS_X)}
        except (OSError, ValueError):
            log.debug("Steering axis has no absinfo; steering will be ignored")
        for code, logical in AXIS_MAP.items():
            if logical == "steering":
                continue
            try:
                info = device.absinfo(code)
            except (OSError, ValueError):
                continue
            if info is None:
                continue
            self._calibrations[code] = _AxisCalibration.from_absinfo(
                int(info.value), int(info.min), int(info.max)
            )
        log.debug(
            "Calibrated pedal axes: %s",
            {AXIS_MAP.get(code, code): cal.rest for code, cal in self._calibrations.items()},
        )

    def _loop(self, device: "InputDevice") -> None:
        while not self.isInterruptionRequested():
            try:
                readable, _, _ = select.select(
                    [device.fd], [], [], self._POLL_TIMEOUT_S
                )
            except (OSError, ValueError) as exc:
                self._emit_disconnect(str(exc))
                return
            if not readable:
                continue

            try:
                events = list(device.read())
            except BlockingIOError:
                continue
            except OSError as exc:
                self._emit_disconnect(str(exc))
                return

            for event in events:
                if event.type == evdev.ecodes.EV_ABS:
                    self._handle_abs(event.code, int(event.value))
                elif event.type == evdev.ecodes.EV_KEY:
                    self._handle_key(event.code, int(event.value))

    def _emit_disconnect(self, reason: str) -> None:
        if not self.isInterruptionRequested():
            log.info("Input stream ended: %s", reason)
            self.disconnected.emit(reason)

    # -- event decoding ---------------------------------------------------
    def _handle_abs(self, code: int, value: int) -> None:
        logical = AXIS_MAP.get(code)
        if logical == "steering":
            try:
                info = self._absinfo_for(code)
            except OSError:
                return
            if info is None:
                return
            minimum, maximum = int(info.min), int(info.max)
            center = (minimum + maximum) / 2.0
            half_span = max(1.0, (maximum - minimum) / 2.0)
            normalized = max(-1.0, min(1.0, (value - center) / half_span))
            self._emit_axis(logical, normalized, value)
            return

        if logical is not None:
            calibration = self._calibrations.get(code)
            if calibration is None:
                return
            self._emit_axis(
                logical, calibration.normalize(value, self._deadzone), value
            )
            return

        hat = HAT_MAP.get(code)
        if hat is None:
            return
        self._update_hat(hat, value)

    def _absinfo_for(self, code: int) -> object | None:
        """Return the cached absinfo for ``code`` when one was captured."""
        return self._steering_absinfo.get(code)

    def _handle_key(self, code: int, value: int) -> None:
        name = CODE_TO_BUTTON.get(code, f"btn_{code:03x}")
        pressed = value != 0
        if pressed and name in self._held_buttons:
            return
        if not pressed and name not in self._held_buttons:
            return
        if pressed:
            self._held_buttons.add(name)
        else:
            self._held_buttons.discard(name)
        self.button_changed.emit(name, pressed)

    def _update_hat(self, axis: str, value: int) -> None:
        """Translate hat values into discrete D-pad button transitions."""
        previous = self._hat_state
        if axis == "dpad_x":
            self._hat_state = (max(-1, min(1, value)), previous[1])
        else:
            self._hat_state = (previous[0], max(-1, min(1, value)))

        pairs = (
            ("dpad_left", previous[0] < 0, self._hat_state[0] < 0),
            ("dpad_right", previous[0] > 0, self._hat_state[0] > 0),
            ("dpad_up", previous[1] < 0, self._hat_state[1] < 0),
            ("dpad_down", previous[1] > 0, self._hat_state[1] > 0),
        )
        for name, was_pressed, is_pressed in pairs:
            if was_pressed == is_pressed:
                continue
            if is_pressed:
                self._held_buttons.add(name)
            else:
                self._held_buttons.discard(name)
            self.button_changed.emit(name, is_pressed)

    def _emit_axis(self, logical: str, value: float, raw: int) -> None:
        previous = self._last_axis_values.get(logical)
        if previous is not None and abs(previous - value) < self._AXIS_EPSILON:
            return
        self._last_axis_values[logical] = value
        self.axis_changed.emit(logical, value, raw)

    # -- public API -------------------------------------------------------
    def stop(self, timeout_ms: int = 2000) -> None:
        """Request interruption and wait briefly for the thread to finish."""
        self.requestInterruption()
        if not self.wait(timeout_ms):
            log.warning("Input reader for %s did not stop in time", self._event_path)

