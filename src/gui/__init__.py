"""PyQt6 presentation layer."""

from __future__ import annotations

__all__ = ["MainWindow"]


def __getattr__(name: str):
    # Imported lazily so ``python -c "import src.gui"`` stays cheap and does not
    # require a display connection.
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    raise AttributeError(name)
