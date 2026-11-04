# G923 Linux Control

**Offline PyQt6 control panel for the Logitech G923 racing wheel on Linux —
force feedback, pedal diagnostics and rev LEDs without background services.**

[![License: MIT](https://img.shields.io/badge/license-MIT-22d3ee.svg)](LICENSE)

G923 Linux Control talks directly to the kernel interfaces that own the wheel:
`evdev` for input, `sysfs` attributes from `hid-lg4ff`/`hid-logitech-hidpp` for
rotation and force feedback, and `hidraw` for the shift-light bar. There is no
daemon, no telemetry upload, no account, and no vendor software to install.

> **Independence notice.** This is an independent open-source project. It is
> not affiliated with, endorsed by, or sponsored by Logitech. The application
> is custom-tailored to the G923 hardware and deliberately avoids vendor
> software names and branding in its package, window title and repository.

---

## Features

### Steering & force feedback

- **270°–900° operating range** with immediate kernel-level application.
- **Overall FFB gain**, **damper strength** and **centering spring** sliders.
- Direct `sysfs` writes: `range`, `gain`, `autocenter`, `spring_level`,
  `damper_level` (exact attributes depend on the loaded driver).
- Capability probe shows which attributes the kernel actually exposes;
  unsupported settings are skipped and reported instead of failing the apply.
- **Oversteer preset export** for users who manage the wheel with Oversteer on
  systems where the kernel attributes are read-only.

### Pedals & real-time input visualizer

- Live throttle, brake and clutch travel with per-axis percentages.
- Auto-calibrated pedal polarity: rest position is sampled when the wheel
  connects, so inverted pedals need no configuration.
- A painted 2D wheel view highlights face buttons, D-pad directions, shoulder
  buttons, dual-clutch paddles, shift paddles and stick clicks as the kernel
  reports them.
- Input is opened **without grabbing** the device — games keep receiving events
  while the diagnostics run.

### Rev LEDs & telemetry hooks

- Custom RPM **colour bands** (green → yellow → red → flashing blue by default)
  with per-band colour and flash toggles.
- Adjustable brightness and update rate, with a live preview strip.
- **Dynamic game-hook loader**: drop a JSON descriptor or Python script into
  `hooks/` (or `~/.config/g923-linux-control/hooks/`) to feed RPM telemetry from
  games that do not drive Logitech LEDs on Linux.
- **Pedal fallback**: when telemetry is missing or stale, throttle travel
  progressively lights the bar, with deadzone and smoothing.
- Honest hardware reporting: the LED sink status tells you whether the
  `hidraw` node was opened and which report family is in use.

### Application qualities

- **Offline and private** — zero network calls, zero telemetry, zero accounts.
- **No daemons** — one foreground GUI process; closing it releases every
  handle.
- **One small config file** — `~/.config/g923-linux-control/settings.json`,
  written atomically with `0600` permissions.
- **Lightweight by design, honest about Qt** — pure Qt widgets and QPainter
  drawing; no Electron, Chromium, web engine, image assets or daemons. The
  complete source tree is **384 KiB**. Resident memory is dominated by the Qt 6
  runtime: on the reference machine a bare `QApplication` measured **70.6 MiB**
  RSS and the fully built four-page dashboard measured **85.2 MiB** (PyQt6
  6.12, `offscreen` platform). A sub-30 MB RSS is not achievable with a
  full Qt desktop runtime, and this project does not hide that baseline.
- **Graceful hardware churn** — hot-plug polling every two seconds, automatic
  reader restart, settings re-applied on reconnect.
- **Safe settings** — every value is validated and clamped; a corrupt JSON file
  is moved aside instead of crashing the app.

---

## Screens (sidebar navigation)

| Page | Purpose |
| --- | --- |
| **Dashboard** | Connection badge, firmware/USB release, driver binding, live pedals, active profile, telemetry state |
| **Steering & Force Feedback** | Rotation, gain, damper, spring, driver capabilities, Oversteer export |
| **Pedals & Inputs** | Pedal meters, steering angle, interactive wheel visualizer |
| **Rev LEDs & Hooks** | Live LED frame, brightness, colour bands, hook picker, fallback toggle, output status |

The header always shows a live **Detected / Disconnected** badge, the firmware
(or USB release) string, and the active profile.

---

## Requirements

### Operating system

- Linux with a reasonably recent kernel (Ubuntu 22.04+, Zorin OS 17+, Debian 12+,
  or any distribution with kernel 6.3+ for the Xbox-mode HID++ binding).
- Python **3.10+**.

### Python packages

```
PyQt6>=6.6,<7.0
evdev>=1.6,<2.0
```

On Debian/Ubuntu/Zorin you can use distribution packages instead of pip
(recommended, because it avoids compiling `evdev`):

```bash
sudo apt update
sudo apt install python3-venv python3-pyqt6 python3-evdev
```

If you install `evdev` from PyPI instead, the build needs the Python headers:
`sudo apt install python3-dev`.

### Kernel driver

`hid-lg4ff` is a **kernel module**, not an apt package. It ships with the
kernel and is normally loaded automatically. Verify:

```bash
lsmod | grep -E 'hid_logitech|hid-lg4ff'
ls /sys/bus/hid/drivers/
```

- **PlayStation/PC mode** (`046d:c266`, `046d:c267`) is handled by
  `hid-lg4ff` (driver name `logitech`) or the optional
  [`new-lg4ff`](https://github.com/berarma/new-lg4ff) DKMS module. The latter
  adds `gain`, `autocenter`, `spring_level`, `damper_level` and more.
- **Xbox/PC mode** (`046d:c26d`, `046d:c26e`) uses the HID++ driver
  (`hid-logitech-hidpp`) and is supported by the in-kernel driver from Linux
  6.3. `new-lg4ff` is **not** compatible with these IDs.
- Some units need the known `usb_modeswitch` udev rule before they enumerate as
  a wheel (especially the Xbox edition). See
  [ArchWiki: Logitech Racing Wheel](https://wiki.archlinux.org/title/Logitech_Racing_Wheel)
  for the exact rule.

The application **does not** install kernel modules, udev rules, or run
anything as root.

---

## Installation

```bash
git clone https://github.com/Pandagamerteen08/g923-linux-control.git
cd g923-linux-control

sudo apt install python3-venv   # once, if the venv module is missing
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Device permissions (recommended)

Reading input usually works through systemd-logind's `uaccess` ACL. Writing
`hidraw` (LEDs) and `sysfs` (FFB) needs a rule. Create
`/etc/udev/rules.d/70-g923-linux-control.rules`:

```udev
# Input events: grant the logged-in user access
KERNEL=="event*", ATTRS{idVendor}=="046d", TAG+="uaccess"

# hidraw LED output for the four G923 USB modes
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c266", MODE="0660", GROUP="input"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c267", MODE="0660", GROUP="input"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c26d", MODE="0660", GROUP="input"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", ATTRS{idProduct}=="c26e", MODE="0660", GROUP="input"
```

Then:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
# reconnect the wheel
```

Add your user to the `input` group if the rule uses `GROUP="input"`:

```bash
sudo usermod -aG input "$USER"
# log out and back in
```

If writes are still refused, the app shows the exact path in the status bar —
that is the attribute or node that needs permission.

---

## Usage

```bash
python main.py
```

Useful flags:

```bash
python main.py --version
python main.py --verbose          # debug logging on stderr
python main.py --no-tray          # no tray icon
python main.py --reset-settings   # rewrite defaults before launching
```

1. Connect the wheel and switch it to the mode you use (PS/PC or Xbox/PC).
2. Start the app. The header badge changes to **Detected** and the dashboard
   lists the driver, input node and firmware/USB release.
3. Open **Steering & Force Feedback** and set rotation and FFB to taste. Changes
   are debounced and written directly to `sysfs`; rotation is re-applied after
   a reconnect.
4. Open **Pedals & Inputs** and press every control. The visualizer highlights
   what the kernel reports. Keep pedals released while plugging in so the rest
   calibration is correct.
5. Open **Rev LEDs & Hooks**. Pick a telemetry hook, or leave it on
   **No telemetry hook** to use the throttle-driven fallback. Tune the colour
   bands and brightness with the preview slider.
6. Closing the window hides it to the tray when a tray host is available.
   Choose **Quit** from the tray menu for a full shutdown.

### Where settings live

```text
~/.config/g923-linux-control/settings.json
```

A single JSON document, no caches, no logs:

```json
{
  "schema": 1,
  "profile": "Default",
  "steering": {
    "rotation_deg": 900,
    "ffb_gain": 100,
    "damper": 100,
    "spring": 100
  },
  "leds": {
    "brightness": 80,
    "bands": [
      { "threshold": 0,  "color": "#21d4a0", "flash": false },
      { "threshold": 55, "color": "#a8e05f", "flash": false },
      { "threshold": 72, "color": "#f2c94c", "flash": false },
      { "threshold": 84, "color": "#ff8a3d", "flash": false },
      { "threshold": 92, "color": "#ff4d5e", "flash": true },
      { "threshold": 98, "color": "#3ea6ff", "flash": true }
    ],
    "fallback_enabled": true,
    "blink_hz": 6.0,
    "update_hz": 30,
    "led_count": 5
  },
  "telemetry": {
    "active_hook": "",
    "poll_interval_ms": 0,
    "stale_timeout_ms": 800,
    "throttle_deadzone": 0.02,
    "max_rpm": 8000
  },
  "ui": {
    "close_to_tray": true,
    "start_minimized": false,
    "last_page": "dashboard",
    "window_width": 1180,
    "window_height": 780
  }
}
```

Hooks live beside the config:

```text
~/.config/g923-linux-control/hooks/
```

---

## Telemetry hooks

The hook system is intentionally file-based so game bridges can be added
without touching the application. The full contract is in
[`hooks/README.md`](hooks/README.md); the short version:

- **JSON hook** — read a telemetry file or run an argv command that prints JSON.
  See [`hooks/snowrunner_file_bridge.json`](hooks/snowrunner_file_bridge.json).
- **Python hook** — expose `HOOK_NAME`, optional `HOOK_DESCRIPTION` /
  `HOOK_INTERVAL_MS`, and `poll()` returning a mapping. See
  [`hooks/example_telemetry_hook.py`](hooks/example_telemetry_hook.py).

Required payload fields are `rpm` and (normally) `max_rpm`; `throttle`, `brake`,
`clutch`, `gear` and `speed_kmh` are optional extras shown in the status line.
Common aliases such as `engineRpm`, `maxRpm` and `ThrottleInput` are recognized
automatically. Each hook declares its own `poll_interval_ms`;
`settings.telemetry.poll_interval_ms` overrides it only when set to a non-zero
value (it defaults to `0`, meaning "use the hook's interval").

Hooks run as trusted local code with your permissions. The app never uploads
telemetry and never listens on a network port.

### Fallback behaviour

When `fallback_enabled` is true and no sample has arrived for
`stale_timeout_ms`, the LED ratio follows throttle travel. The transition is
automatic and shown in the status line. Feedback is smoothed so potentiometer
noise does not flicker the bar.

### LED hardware notes

The wheel's shift-light bar is driven as a **bitmask**:

- PlayStation/PC modes: classic HID report `F8 12 <bits> 00 00 00 01`.
- Xbox/PC modes: HID++ short report `11 FF 12 51 00 05 <bits>` after a one-time
  `11 FF 12 31 00` handshake.

The bar itself is monochrome; RGB band colours and brightness are rendered in
the preview, and flashing is transmitted by toggling the bitmask. If no
`hidraw` node is found, the LEDs section says so — the rest of the application
continues to work.

---

## Architecture

```text
.
├── main.py                     # entry point, signals, tray, shutdown
├── requirements.txt
├── README.md
├── LICENSE
├── assets/
│   └── style.qss               # dark slate theme (#18191c) and widget styling
├── hooks/
│   ├── README.md               # hook contract
│   ├── example_telemetry_hook.py
│   └── snowrunner_file_bridge.json
├── src/
│   ├── app.py                  # composition root, debounced persistence/apply
│   ├── config.py               # validated dataclasses + atomic JSON storage
│   ├── constants.py            # USB IDs, evdev mapping, colour tokens
│   ├── hardware/
│   │   ├── device.py           # evdev/hidraw/sysfs discovery, firmware readout
│   │   ├── evdev_reader.py     # QThread input stream, pedal auto-calibration
│   │   ├── leds.py             # classic HID + HID++ hidraw LED sink
│   │   ├── oversteer.py        # Oversteer detection and preset export
│   │   ├── service.py          # hot-plug, reader lifecycle, driver applies
│   │   └── sysfs.py            # capability probe and sysfs writes
│   ├── telemetry/
│   │   ├── fallback.py         # throttle → LED ratio with smoothing
│   │   ├── hooks.py            # hook discovery, parsing and polling thread
│   │   ├── led_controller.py   # frame timer → wheel writes + UI signal
│   │   ├── led_engine.py       # bands → colours/bitmask (pure, testable)
│   │   └── service.py          # telemetry/fallback state machine
│   └── gui/
│       ├── dashboard.py
│       ├── icons.py            # QPainter-drawn application icon
│       ├── leds.py             # band editor and hook picker
│       ├── main_window.py      # header, sidebar, page wiring
│       ├── pedals.py
│       ├── steering.py
│       ├── theme.py
│       ├── tray.py
│       ├── wheel_visualizer.py # painted wheel/input diagram
│       └── widgets.py          # cards, sliders, meter bars, LED strip, badge
```

### Design notes

- The GUI never touches `/dev` or `/sys`; it emits signals through
  `ApplicationContext`.
- Input decoding and hook polling run in QThreads. LED writes are synchronous
  and coalesced (one `os.write` per changed frame).
- `sysfs` and hook failures are reported, not swallowed: the status bar and the
  relevant page show the exact problem.
- Settings are the single source of truth; every mutation is normalized before
  saving.
- The LED engine is pure Python and can be tested without Qt or hardware.

---

## Building a standalone binary

[PyInstaller](https://pyinstaller.org/) can package the app. Use a virtual
environment so the build does not pull unrelated packages in.

```bash
python -m pip install pyinstaller
pyinstaller \
  --noconfirm \
  --windowed \
  --name g923-linux-control \
  --add-data "assets:assets" \
  --add-data "hooks:hooks" \
  main.py
```

The result is `dist/g923-linux-control/g923-linux-control`. Run it from a
terminal to see log output:

```bash
./dist/g923-linux-control/g923-linux-control --verbose
```

Notes:

- PyInstaller bundles Qt, so the distribution directory is considerably larger
  than the source tree (tens of MB). For the smallest installation, run from
  source with the distribution's `python3-pyqt6` package instead.
- The bundled `hooks/` directory is a read-only template. User hooks in
  `~/.config/g923-linux-control/hooks/` always take effect and are not
  overwritten.
- A `.desktop` launcher can point at the built executable; the app sets its
  desktop file name to `g923-linux-control`.

### Development checks

```bash
python -m compileall -q main.py src
QT_QPA_PLATFORM=offscreen python main.py --no-tray &
sleep 3
kill %1
```

---

## Troubleshooting

**The wheel is not detected**

- `lsusb | grep 046d` — confirm the product ID is one of `c266`, `c267`,
  `c26d`, `c26e`.
- `evtest` should list a node with `ABS_X` and the wheel buttons. If it does
  not, the wheel is still in the wrong USB mode (see the `usb_modeswitch` rule)
  or bound to `hid-generic`.
- `lsmod | grep logitech` and `ls /sys/bus/hid/drivers/` show the active
  binding.
- If the badge stays **Disconnected** but `evdev` works, check the app's stderr
  with `--verbose`; permission errors include the exact remediation.

**Rotation changes, but gain/damper/spring are "unsupported"**

The in-tree HID++ binding exposes fewer knobs than `new-lg4ff`. Install the
DKMS module for the PlayStation/PC variant, or accept range-only control on
Xbox mode. The steering page lists every attribute the kernel actually exposes.

**The rev bar does not light**

- Hooks page → *Hardware output* says whether a `hidraw` node was opened.
- Check `ls -l /dev/hidraw*` and the udev rule above.
- On the Xbox variant the HID++ handshake is sent when the sink opens; if the
  bar stays dark, include the app's stderr from `--verbose` in an issue.
- The preview strip and the pedal fallback are independent of the hardware
  sink, so you can still validate band behaviour.

**A pedal reads inverted**

Unplug and replug the wheel with all pedals released. Rest calibration happens
when the input node opens; a pedal held at connect time becomes the reference.

**A Python hook crashes or blocks**

The hook runs in its own thread. Exceptions are shown on the LEDs page and the
pedal fallback takes over. A blocking `poll()` cannot be interrupted gracefully
— keep hooks non-blocking and fast.

**High CPU**

Set a larger `poll_interval_ms` in the hook or a lower `leds.update_hz` in
`settings.json`. The LED loop coalesces unchanged frames, so an idle bar costs
almost nothing.

---

## Privacy

- No networking code exists in the application.
- No analytics, crash reporting, accounts or identifiers.
- No log files or caches are written. Logging goes to stderr only.
- The only persistent artifact is `~/.config/g923-linux-control/settings.json`
  (plus hook files and Oversteer presets you explicitly create).

---

## Repository description (GitHub “About”)

> **Offline PyQt6 control panel for the Logitech G923 on Linux — direct kernel force feedback, pedal diagnostics, rev-LED telemetry hooks, and zero background services.**

Suggested topics: `linux`, `pyqt6`, `racing-wheel`, `logitech-g923`, `evdev`,
`hidraw`, `sysfs`, `sim-racing`, `force-feedback`, `telemetry`.

Alternative shorter description:

> Native Linux control utility for the G923 wheel: FFB, pedals, rev LEDs.

---

## Contributing

Issues and pull requests are welcome. Please include:

- distribution and kernel version (`uname -r`),
- wheel USB mode and product ID (`lsusb`),
- loaded driver (`lsmod`),
- relevant app stderr from `python main.py --verbose`.

Keep the project dependency-light and offline-first; new runtime dependencies
need a clear justification.

---

## License

[MIT](LICENSE) © 2026 Pandagamerteen08.

Logitech and G923 are trademarks of their respective owners. This project is
independent and is not affiliated with Logitech.
