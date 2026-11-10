"""Core services for Jack's LML Companion.

UI code lives under ``ui`` and should call these services instead of touching
the game folder itself.
"""

from __future__ import annotations

import sys
from pathlib import Path


class CompanionError(Exception):
    """Expected failure that the window can show to the user."""


class GameDirectoryError(CompanionError):
    """The selected folder is not an RDR2 install."""


def app_data_dir() -> Path:
    """Directory for config, manifests, and staging data.

    Development builds keep this in the project root. A packaged executable
    keeps it beside the .exe so one-file extraction does not wipe it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def assert_within(parent: Path, child: Path) -> Path:
    """Return the resolved child, or raise if it escapes ``parent``."""
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise CompanionError(f"Path escapes the allowed folder: {child}") from exc
    return child_resolved


def path_key(path: Path) -> str:
    """Identity key for a path, case-insensitive on Windows."""
    text = str(path.resolve())
    return text.casefold() if sys.platform == "win32" else text
