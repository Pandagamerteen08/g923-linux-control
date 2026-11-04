"""Plug-and-play telemetry hooks.

A hook is either a Python file or a JSON descriptor dropped into ``hooks/``
(project directory) or ``~/.config/g923-linux-control/hooks/`` (user directory):

JSON descriptor
    Declarative, safe to inspect and share::

        {
          "schema": "g923-linux-control/hook@1",
          "name": "SnowRunner telemetry bridge",
          "description": "Reads a JSON file written by a telemetry bridge mod.",
          "poll_interval_ms": 100,
          "source": {"type": "file", "path": "~/.local/share/…/telemetry.json"},
          "fields": {"rpm": "engineRpm", "max_rpm": "maxRpm", "throttle": "throttle"}
        }

    ``source.type`` may also be ``command`` with an argv list; the command must
    print one JSON object to stdout.

Python hook
    Executed as ordinary local code in a polling thread::

        HOOK_NAME = "My game bridge"
        HOOK_DESCRIPTION = "…"
        HOOK_INTERVAL_MS = 100

        def poll() -> dict:
            return {"rpm": 4200, "max_rpm": 7000, "throttle": 0.6}

Hooks are *trusted local code* — no sandbox is attempted.  Discovery uses
:mod:`ast` for Python metadata so importing a hook is never a side effect of
opening the settings page.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PyQt6.QtCore import QThread, pyqtSignal

from ..config import default_config_dir

log = logging.getLogger(__name__)

HOOK_SCHEMA = "g923-linux-control/hook@1"
_VALID_SOURCE_TYPES = frozenset({"file", "command"})


class HookError(RuntimeError):
    """Base class for hook loading and evaluation failures."""


class HookSourceError(HookError):
    """The hook exists but its data source is not ready (file missing, etc.)."""


class HookPayloadError(HookError):
    """The hook produced data that cannot be interpreted."""


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """One normalized telemetry reading.

    Only ``rpm`` and ``max_rpm`` are needed to drive the LEDs; the remaining
    fields enrich the status readout.
    """

    rpm: float | None = None
    max_rpm: float | None = None
    throttle: float | None = None
    brake: float | None = None
    clutch: float | None = None
    gear: int | None = None
    speed_kmh: float | None = None
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def ratio(self) -> float | None:
        """Engine load in ``0.0–1.0``, or ``None`` when RPM is unknown."""
        if self.rpm is None:
            return None
        maximum = self.max_rpm if self.max_rpm and self.max_rpm > 0 else 0.0
        if maximum <= 0:
            return None
        return max(0.0, min(1.0, self.rpm / maximum))

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.rpm is not None:
            if self.max_rpm:
                parts.append(f"{self.rpm:.0f} / {self.max_rpm:.0f} rpm")
            else:
                parts.append(f"{self.rpm:.0f} rpm")
        if self.gear:
            parts.append(f"gear {self.gear}")
        if self.speed_kmh is not None:
            parts.append(f"{self.speed_kmh:.0f} km/h")
        return " · ".join(parts) or "no engine data"


# ---------------------------------------------------------------------------
# Hook descriptions
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class HookSpec:
    """Metadata required to display and run a hook."""

    id: str
    name: str
    description: str
    kind: str
    path: Path
    poll_interval_ms: int = 100
    source_type: str = ""
    source_path: str = ""
    command: tuple[str, ...] = ()
    fields: Mapping[str, str] = field(default_factory=dict)
    warning: str = ""

    @property
    def kind_label(self) -> str:
        return "Python" if self.kind == "python" else "JSON"

    @property
    def source_label(self) -> str:
        if self.kind == "python":
            return self.path.name
        if self.source_type == "file":
            return self.source_path
        if self.source_type == "command":
            return " ".join(self.command)
        return self.path.name


@dataclass(frozen=True, slots=True)
class HookCatalog:
    """Result of scanning the hook directories."""

    hooks: tuple[HookSpec, ...] = ()
    warnings: tuple[str, ...] = ()

    def find(self, hook_id: str) -> HookSpec | None:
        for hook in self.hooks:
            if hook.id == hook_id:
                return hook
        return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def default_hook_dirs() -> tuple[Path, Path]:
    """Return the project hook directory and the per-user hook directory."""
    package_root = Path(__file__).resolve().parents[2]
    bundled = Path(getattr(os.sys, "_MEIPASS", package_root))  # type: ignore[attr-defined]
    return (bundled / "hooks", default_config_dir() / "hooks")


def _python_metadata(path: Path) -> tuple[dict[str, Any], str]:
    """Read hook metadata with :mod:`ast` without executing the module."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError) as exc:
        return {}, f"{path.name}: {exc}"

    values: dict[str, Any] = {}
    has_poll = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "poll":
                if isinstance(node, ast.AsyncFunctionDef):
                    return {}, f"{path.name}: async poll() is not supported"
                has_poll = True
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "HOOK_NAME",
                "HOOK_DESCRIPTION",
                "HOOK_INTERVAL_MS",
            }:
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue

    if not has_poll:
        return values, f"{path.name}: no poll() function found"
    return values, ""


def _python_spec(path: Path) -> tuple[HookSpec | None, str]:
    metadata, warning = _python_metadata(path)
    interval = metadata.get("HOOK_INTERVAL_MS", 100)
    try:
        interval_ms = max(16, min(1000, int(interval)))
    except (TypeError, ValueError):
        interval_ms = 100
    spec = HookSpec(
        id=str(path.resolve()),
        name=str(metadata.get("HOOK_NAME") or path.stem.replace("_", " ").title()),
        description=str(metadata.get("HOOK_DESCRIPTION") or ""),
        kind="python",
        path=path,
        poll_interval_ms=interval_ms,
        warning=warning,
    )
    if warning:
        return None, warning
    return spec, ""


def _json_spec(path: Path) -> tuple[HookSpec | None, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}: {exc}"

    if not isinstance(document, dict):
        return None, f"{path.name}: hook root must be a JSON object"
    source = document.get("source")
    if not isinstance(source, dict):
        return None, f"{path.name}: missing 'source' object"

    source_type = str(source.get("type", "")).lower()
    if source_type not in _VALID_SOURCE_TYPES:
        return None, f"{path.name}: source.type must be 'file' or 'command'"

    source_path = ""
    command: tuple[str, ...] = ()
    if source_type == "file":
        raw_path = source.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None, f"{path.name}: source.path must be a non-empty string"
        source_path = raw_path.strip()
    else:
        raw_command = source.get("command")
        if isinstance(raw_command, str):
            command = tuple(shlex.split(raw_command))
        elif isinstance(raw_command, list) and all(
            isinstance(part, str) for part in raw_command
        ):
            command = tuple(raw_command)
        if not command:
            return None, f"{path.name}: source.command must be a non-empty argv list"

    fields_raw = document.get("fields")
    fields: dict[str, str] = {}
    if isinstance(fields_raw, dict):
        fields = {
            str(key): str(value)
            for key, value in fields_raw.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    try:
        interval_ms = max(16, min(1000, int(document.get("poll_interval_ms", 100))))
    except (TypeError, ValueError):
        interval_ms = 100

    spec = HookSpec(
        id=str(path.resolve()),
        name=str(document.get("name") or path.stem.replace("_", " ").title()),
        description=str(document.get("description") or ""),
        kind="json",
        path=path,
        poll_interval_ms=interval_ms,
        source_type=source_type,
        source_path=source_path,
        command=command,
        fields=fields,
    )
    return spec, ""


def discover_hooks(
    directories: Sequence[Path] | None = None,
) -> HookCatalog:
    """Scan hook directories for Python and JSON telemetry sources."""
    search_dirs = tuple(directories) if directories is not None else default_hook_dirs()
    hooks: list[HookSpec] = []
    warnings: list[str] = []
    seen: set[Path] = set()

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name.lower())
        except OSError as exc:
            warnings.append(f"Could not read hook directory {directory}: {exc}")
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in {".py", ".json"}:
                continue
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)

            if path.suffix.lower() == ".py":
                spec, warning = _python_spec(path)
            else:
                spec, warning = _json_spec(path)
            if warning:
                warnings.append(warning)
            if spec is not None:
                hooks.append(spec)

    hooks.sort(key=lambda hook: (hook.kind != "python", hook.name.lower()))
    return HookCatalog(hooks=tuple(hooks), warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# Sample parsing
# ---------------------------------------------------------------------------
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "rpm": ("rpm", "RPM", "engineRpm", "engine_rpm", "EngineRPM", "Rpms", "rpm_current"),
    "max_rpm": (
        "max_rpm",
        "maxRpm",
        "maxRPM",
        "MaxRpm",
        "rpm_max",
        "redline",
        "Redline",
    ),
    "throttle": ("throttle", "Throttle", "throttle_input", "ThrottleInput", "gas"),
    "brake": ("brake", "Brake", "brake_input", "BrakeInput"),
    "clutch": ("clutch", "Clutch", "clutch_input", "ClutchInput"),
    "gear": ("gear", "Gear", "gear_index"),
    "speed_kmh": ("speed_kmh", "speedKmh", "SpeedKmh", "speed", "Speed"),
}


def _lookup(
    data: Mapping[str, Any],
    standard_name: str,
    fields: Mapping[str, str],
) -> Any:
    """Find a value by the hook's field map, then by common aliases."""
    override = fields.get(standard_name)
    if override and override in data:
        return data[override]
    for key in _FIELD_CANDIDATES[standard_name]:
        if key in data:
            return data[key]
    return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _to_unit(value: Any) -> float | None:
    number = _to_float(value)
    if number is None:
        return None
    if 1.0 < number <= 100.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def parse_sample(
    raw: Any,
    fields: Mapping[str, str] | None = None,
    default_max_rpm: int = 8000,
) -> TelemetrySample | None:
    """Normalize arbitrary hook output into a :class:`TelemetrySample`.

    Returns ``None`` when the payload has neither RPM nor throttle data, which
    lets the poller report a useful error instead of silently driving nothing.
    """
    if isinstance(raw, TelemetrySample):
        return raw
    if not isinstance(raw, Mapping):
        return None
    data: Mapping[str, Any] = raw
    nested = raw.get("telemetry")
    if isinstance(nested, Mapping):
        data = nested

    mapping = fields or {}
    rpm = _to_float(_lookup(data, "rpm", mapping))
    max_rpm = _to_float(_lookup(data, "max_rpm", mapping))
    throttle = _to_unit(_lookup(data, "throttle", mapping))
    if rpm is None and throttle is None:
        return None

    if max_rpm is None or max_rpm <= 0:
        max_rpm = float(default_max_rpm)
    elif max_rpm < 100:
        # Hooks occasionally expose a 0–1 fraction; treat anything tiny as a
        # fraction of a realistic redline rather than a 3 RPM engine.
        max_rpm = float(default_max_rpm)

    gear_raw = _lookup(data, "gear", mapping)
    gear: int | None = None
    if gear_raw is not None:
        try:
            gear = int(gear_raw)
        except (TypeError, ValueError):
            gear = None

    return TelemetrySample(
        rpm=rpm,
        max_rpm=max_rpm,
        throttle=throttle,
        brake=_to_unit(_lookup(data, "brake", mapping)),
        clutch=_to_unit(_lookup(data, "clutch", mapping)),
        gear=gear,
        speed_kmh=_to_float(_lookup(data, "speed_kmh", mapping)),
    )


# ---------------------------------------------------------------------------
# Polling thread
# ---------------------------------------------------------------------------
def _expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


def _load_python_poll(path: Path) -> Callable[[], Any]:
    """Import a Python hook file and return its ``poll`` callable."""
    module_name = f"g923_hook_{abs(hash(str(path))) & 0xFFFFFF:x}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise HookError(f"Could not load hook module {path.name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # user code: surface the real error
        raise HookError(f"Importing {path.name} failed: {exc}") from exc
    poll = getattr(module, "poll", None)
    if not callable(poll):
        raise HookError(f"{path.name} does not define poll()")
    return poll


class HookPoller(QThread):
    """Poll one hook in a background thread and emit normalized samples."""

    sample = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        spec: HookSpec,
        interval_ms: int = 100,
        default_max_rpm: int = 8000,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._spec = spec
        self._interval = max(16, min(1000, int(interval_ms))) / 1000.0
        self._default_max_rpm = default_max_rpm
        self._last_error = ""

    # -- thread body ------------------------------------------------------
    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            read = self._build_reader()
        except Exception as exc:
            self.error.emit(str(exc))
            return

        while not self.isInterruptionRequested():
            started = time.monotonic()
            try:
                raw = read()
                if raw is None:
                    raise HookSourceError("hook returned no data yet")
                sample = parse_sample(raw, self._spec.fields, self._default_max_rpm)
                if sample is None:
                    raise HookPayloadError(
                        "hook payload has no rpm or throttle fields"
                    )
                self.sample.emit(sample)
                self._last_error = ""
            except HookSourceError as exc:
                self._report_error(str(exc))
            except Exception as exc:
                self._report_error(str(exc) or exc.__class__.__name__)

            elapsed = time.monotonic() - started
            self._sleep(max(0.0, self._interval - elapsed))

    def _build_reader(self) -> Callable[[], Any]:
        spec = self._spec
        if spec.kind == "python":
            return _load_python_poll(spec.path)
        if spec.kind == "json" and spec.source_type == "file":
            path = _expand(spec.source_path)

            def read_file() -> Any:
                try:
                    text = path.read_text(encoding="utf-8")
                except FileNotFoundError as exc:
                    raise HookSourceError(f"waiting for {path}") from exc
                except OSError as exc:
                    raise HookSourceError(f"could not read {path}: {exc}") from exc
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise HookPayloadError(f"invalid JSON in {path}: {exc}") from exc

            return read_file
        if spec.kind == "json" and spec.source_type == "command":
            argv = [
                os.path.expandvars(os.path.expanduser(part)) for part in spec.command
            ]

            def run_command() -> Any:
                try:
                    completed = subprocess.run(
                        argv,
                        capture_output=True,
                        text=True,
                        timeout=1.5,
                        check=False,
                    )
                except FileNotFoundError as exc:
                    raise HookError(f"command not found: {argv[0]}") from exc
                except subprocess.TimeoutExpired as exc:
                    raise HookSourceError("hook command timed out") from exc
                if completed.returncode != 0:
                    detail = (completed.stderr or "").strip().splitlines()
                    suffix = f": {detail[-1]}" if detail else ""
                    raise HookError(
                        f"hook command exited {completed.returncode}{suffix}"
                    )
                try:
                    return json.loads(completed.stdout)
                except json.JSONDecodeError as exc:
                    raise HookPayloadError(
                        f"hook command did not print JSON: {exc}"
                    ) from exc

            return run_command
        raise HookError(f"Unsupported hook source: {spec.kind}/{spec.source_type}")

    def _report_error(self, message: str) -> None:
        if message != self._last_error:
            self._last_error = message
            self.error.emit(message)

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.isInterruptionRequested():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.02, remaining))

    # -- lifecycle --------------------------------------------------------
    def stop(self, timeout_ms: int = 2500) -> None:
        self.requestInterruption()
        if not self.wait(timeout_ms):
            log.warning("Hook poller for %s did not stop in time", self._spec.name)
