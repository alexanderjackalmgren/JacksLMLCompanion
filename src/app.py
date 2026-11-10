"""Application entry point.

Run from the project root:

    python src/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core import resource_dir
from core.analyzer import ModAnalyzer
from core.collision import CollisionDetector
from core.diagnostics import CrashDiagnostics
from core.infrastructure import InfrastructureManager, load_config
from core.manifest import ManifestStore
from core.profiles import ProfileSwitcher
from ui.main_window import MainWindow
from version import __version__

APP_NAME = "Jack's LML Companion"
APP_VERSION = __version__


def _app_icon() -> QIcon:
    root = resource_dir()
    for relative in (
        Path("assets") / "app_icon.ico",
        Path("assets") / "app_icon.png",
    ):
        candidate = root / relative
        if candidate.is_file():
            return QIcon(str(candidate))
    return QIcon()


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setStyle("Fusion")
    icon = _app_icon()
    if not icon.isNull():
        application.setWindowIcon(icon)
    window = MainWindow(
        config=load_config(),
        infrastructure=InfrastructureManager(),
        diagnostics=CrashDiagnostics(),
        profiles=ProfileSwitcher(),
        manifests=ManifestStore(),
        analyzer=ModAnalyzer(),
        collisions=CollisionDetector(),
    )
    window.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
