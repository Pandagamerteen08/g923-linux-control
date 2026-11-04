"""Rev-LED output over ``hidraw``.

Two reports are used, matching how the wheel's two USB families expect to be
addressed:

* PlayStation/PC modes (``0xc266`` / ``0xc267``): classic HID output report
  ``F8 12 <bits> 00 00 00 01``.
* Xbox/PC modes (``0xc26d`` / ``0xc26e``): HID++ short reports.  A one-time
  handshake switches the bar to direct-control mode, after which the bitmask
  is sent in the last byte of ``11 FF 12 51 00 05 <bits>``.

The LED bar is written as a bitmask, so brightness and per-LED colours are
rendered in the on-screen preview; the hardware bar itself is monochrome on
these wheels.  All writes are best-effort: a closed or unplugged device simply
disables the sink and reports why in the UI.
"""

from __future__ import annotations

import logging
import os

from .device import PERMISSION_HINT

log = logging.getLogger(__name__)

PROTOCOL_CLASSIC = "classic"
PROTOCOL_HIDPP = "hidpp"

_CLASSIC_BITMASK_MAX = 0xFF
_HIDPP_PRODUCT_IDS = frozenset({0xC26D, 0xC26E})


def protocol_for_product(product_id: int) -> str:
    """Return the LED report family used by ``product_id``."""
    return PROTOCOL_HIDPP if product_id in _HIDPP_PRODUCT_IDS else PROTOCOL_CLASSIC


def _classic_report(bits: int) -> bytes:
    return bytes((0xF8, 0x12, bits & _CLASSIC_BITMASK_MAX, 0x00, 0x00, 0x00, 0x01))


def _hidpp_setup_report() -> bytes:
    return bytes((0x11, 0xFF, 0x12, 0x31, 0x00))


def _hidpp_led_report(bits: int) -> bytes:
    return bytes(
        (0x11, 0xFF, 0x12, 0x51, 0x00, 0x05, bits & _CLASSIC_BITMASK_MAX)
    )


class LedSink:
    """Write rev-LED bitmasks to ``/dev/hidrawN``.

    The sink is intentionally tiny and synchronous: one ``os.write`` per
    change, no threads, no buffers.  That keeps the LED loop deterministic and
    makes failures easy to attribute.
    """

    def __init__(self, hidraw_path: str, protocol: str, product_id: int = 0) -> None:
        self._path = hidraw_path
        self._protocol = protocol
        self._product_id = product_id
        self._fd: int | None = None
        self._last_bits = -1
        self._error = ""
        self._handshake_done = False

    # -- state ------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._fd is not None

    @property
    def path(self) -> str:
        return self._path

    @property
    def protocol(self) -> str:
        return self._protocol

    @property
    def last_error(self) -> str:
        return self._error

    @property
    def status_text(self) -> str:
        if self.available:
            label = "HID++" if self._protocol == PROTOCOL_HIDPP else "classic HID"
            return f"LED output active → {self._path} ({label})"
        if not self._path:
            return (
                "No hidraw LED node found. Connect the wheel; if it is connected, "
                "the hid-logitech driver may not expose the bar."
            )
        if self._error:
            return self._error
        return f"LED output idle ({self._path})"

    # -- lifecycle --------------------------------------------------------
    def open(self) -> bool:
        """Open the hidraw node and perform the HID++ handshake if needed."""
        self.close()
        if not self._path:
            self._error = "No hidraw node is available for LED output."
            return False
        try:
            fd = os.open(self._path, os.O_WRONLY | os.O_NONBLOCK)
        except PermissionError:
            self._error = f"Permission denied for {self._path}. {PERMISSION_HINT}"
            log.warning("Permission denied opening %s", self._path)
            return False
        except OSError as exc:
            self._error = f"Could not open {self._path}: {exc}"
            log.warning("Could not open %s: %s", self._path, exc)
            return False

        self._fd = fd
        self._error = ""
        self._last_bits = -1
        self._handshake_done = False
        if self._protocol == PROTOCOL_HIDPP:
            try:
                os.write(fd, _hidpp_setup_report())
            except OSError as exc:
                self._error = f"HID++ handshake failed: {exc}"
                log.warning("HID++ LED handshake failed: %s", exc)
                self.close()
                return False
            self._handshake_done = True
        log.info("LED sink ready on %s (%s)", self._path, self._protocol)
        return True

    def send(self, bits: int) -> bool:
        """Send one bitmask; repeated identical values are coalesced."""
        bits &= _CLASSIC_BITMASK_MAX
        if self._fd is None:
            return False
        if bits == self._last_bits:
            return True
        report = (
            _hidpp_led_report(bits)
            if self._protocol == PROTOCOL_HIDPP
            else _classic_report(bits)
        )
        try:
            os.write(self._fd, report)
        except OSError as exc:
            self._error = f"LED write failed: {exc}"
            log.warning("LED write failed on %s: %s", self._path, exc)
            self.close(clear=False)
            return False
        self._last_bits = bits
        return True

    def clear(self) -> None:
        """Turn the bar off, ignoring errors from a vanished device."""
        if self._fd is None:
            return
        try:
            self.send(0)
        except OSError:  # pragma: no cover - send already guards
            pass
        self._last_bits = 0

    def close(self, clear: bool = True) -> None:
        """Optionally clear the bar, then release the descriptor."""
        if self._fd is None:
            return
        if clear:
            self.clear()
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None
        self._handshake_done = False

