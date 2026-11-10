"""Main window: mod library, installer, infrastructure, and diagnostics."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QObject, QPropertyAnimation, QRectF, QUrl, Qt, QThread, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import CompanionError, resource_dir
from core.analyzer import ModAnalyzer
from core.collision import REINSTALL, CollisionDetector
from core.diagnostics import CrashDiagnostics
from core.infrastructure import (
    DLSS_TWEAKS_PACKAGE,
    OPTIONAL_ADDONS,
    STANDARD_PACKAGES,
    AppConfig,
    InfrastructureManager,
    InstallMissingResult,
    PackageSource,
    save_config,
)
from core.manifest import ManifestStore, ModManifest
from core.profiles import Profile, ProfileSwitcher

_STYLE = """
QMainWindow, QWidget { background: #1c1b19; color: #f2efe9; }
QTabWidget::pane { border: 1px solid #3a342c; }
QTabBar::tab { background: #2a2622; color: #f2efe9; padding: 8px 16px; }
QTabBar::tab:selected { background: #3d3428; color: #f0d7a4; }
QPushButton { background: #3d3428; color: #f2efe9; border: 1px solid #6b5840; padding: 6px 12px; }
QPushButton:hover { background: #4d4032; }
QPushButton:disabled { color: #8a8175; border-color: #3a342c; }
QLineEdit, QPlainTextEdit, QTableWidget {
    background: #141311;
    color: #f2efe9;
    border: 1px solid #3a342c;
    selection-background-color: #4d4032;
}
QHeaderView::section { background: #2a2622; color: #f0d7a4; border: none; padding: 6px; }
"""

_MODE_OFF_LABEL = "Modded Storymode"
_MODE_ON_LABEL = "Disabled/Online Mode"
_BANNER_HEIGHT = 160
_BANNER_STORY_CANDIDATES = (
    Path("assets") / "library_hero_storymode.tif",
    Path("library_hero_storymode.tif"),
)
_BANNER_ONLINE_CANDIDATES = (
    Path("assets") / "library_hero_onlinemode.tif",
    Path("library_hero_onlinemode.tif"),
)

_STATE_COLORS = {
    "present": QColor("#b7d3b0"),
    "quarantined": QColor("#e6c98a"),
    "missing": QColor("#e0a090"),
}


def _resolve_banner_path(candidates: tuple[Path, ...]) -> Path | None:
    root = resource_dir()
    for relative in candidates:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def _load_banner_pixmap(candidates: tuple[Path, ...]) -> QPixmap | None:
    path = _resolve_banner_path(candidates)
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    return None if pixmap.isNull() else pixmap


class HeroBanner(QLabel):
    """Full-width banner strip scaled to the window width."""

    def __init__(
        self,
        story: QPixmap,
        online: QPixmap | None = None,
        height: int = _BANNER_HEIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._story = story
        self._online = online if online is not None and not online.isNull() else story
        self._online_mode = False
        self._source = self._story
        self.setFixedHeight(height)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: #141311; border: none;")
        self._refresh()

    def set_online_mode(self, online: bool) -> None:
        online = bool(online)
        source = self._online if online else self._story
        if self._online_mode == online and source.cacheKey() == self._source.cacheKey():
            return
        self._online_mode = online
        self._source = source
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if self._source.isNull() or self.width() <= 0:
            return
        scaled = self._source.scaled(
            self.width(),
            self.height(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - self.width()) // 2)
        y = max(0, (scaled.height() - self.height()) // 2)
        self.setPixmap(scaled.copy(x, y, self.width(), self.height()))


class SlideToggle(QWidget):
    """Pill-shaped on/off switch with a sliding thumb."""

    toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(52, 28)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, *, animate: bool = True) -> None:
        checked = bool(checked)
        if self._checked == checked:
            self._set_offset(1.0 if checked else 0.0, animate=False)
            return
        self._checked = checked
        self._set_offset(1.0 if checked else 0.0, animate=animate)
        self.toggled.emit(checked)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        radius = track.height() / 2
        track_color = QColor("#6b5840") if self._checked else QColor("#3a342c")
        painter.setPen(QPen(QColor("#8a6f4d"), 1))
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(track, radius, radius)

        margin = 3.0
        thumb_size = track.height() - margin * 2
        travel = track.width() - thumb_size - margin * 2
        x = track.x() + margin + travel * self._offset
        y = track.y() + margin
        thumb = QRectF(x, y, thumb_size, thumb_size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#f0d7a4")))
        path = QPainterPath()
        path.addEllipse(thumb)
        painter.drawPath(path)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = max(0.0, min(1.0, float(value)))
        self.update()

    offset = pyqtProperty(float, fget=get_offset, fset=set_offset)

    def _set_offset(self, value: float, *, animate: bool) -> None:
        self._anim.stop()
        if not animate:
            self.set_offset(value)
            return
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(value)
        self._anim.start()


class _ManualPackageRequest:
    def __init__(self, package: PackageSource) -> None:
        self.package = package
        self.path: Path | None = None
        self.event = threading.Event()


class InstallMissingWorker(QObject):
    progress = pyqtSignal(str)
    need_manual = pyqtSignal(object)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, manager: InfrastructureManager, game_dir: Path) -> None:
        super().__init__()
        self._manager = manager
        self._game_dir = game_dir

    def run(self) -> None:
        try:
            result = self._manager.install_missing(
                self._game_dir,
                on_manual_needed=self._request_manual,
                progress=self.progress.emit,
            )
        except CompanionError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface unexpected worker failures
            self.failed.emit(f"Unexpected infrastructure error: {exc}")
            return
        self.finished.emit(result)

    def _request_manual(self, package: PackageSource) -> Path | None:
        request = _ManualPackageRequest(package)
        self.need_manual.emit(request)
        request.event.wait()
        return request.path


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        infrastructure: InfrastructureManager,
        diagnostics: CrashDiagnostics,
        profiles: ProfileSwitcher,
        manifests: ManifestStore,
        analyzer: ModAnalyzer,
        collisions: CollisionDetector,
    ) -> None:
        super().__init__()
        self.config = config
        self.infrastructure = infrastructure
        self.diagnostics = diagnostics
        self.profiles = profiles
        self.manifests = manifests
        self.analyzer = analyzer
        self.collisions = collisions
        self._infra_thread: QThread | None = None
        self._infra_worker: InstallMissingWorker | None = None
        self._pending_manual: _ManualPackageRequest | None = None
        self._install_queue: list[Path] = []
        self._install_busy = False
        self._install_results: list[tuple[str, str]] = []
        self._offer_dlss_after_infra = False
        self.hero_banner: HeroBanner | None = None
        self.resize(1080, 860)
        self.setStyleSheet(_STYLE)
        self.setStatusBar(QStatusBar())
        self._build()
        QTimer.singleShot(0, self._startup)

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(self._build_header())
        self.hero_banner = self._build_banner()
        if self.hero_banner is not None:
            layout.addWidget(self.hero_banner)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_mods_tab(), "Mods")
        self.tabs.addTab(self._build_install_tab(), "Install")
        self.tabs.addTab(self._build_infrastructure_tab(), "Infrastructure")
        self.tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        layout.addWidget(self.tabs, stretch=1)
        self._sync_mode_toggle()

    def _build_banner(self) -> HeroBanner | None:
        story = _load_banner_pixmap(_BANNER_STORY_CANDIDATES)
        online = _load_banner_pixmap(_BANNER_ONLINE_CANDIDATES)
        if story is None and online is None:
            return None
        if story is None:
            story = online
        assert story is not None
        return HeroBanner(story, online=online, height=_BANNER_HEIGHT)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("RDR2 folder"))
        self.game_path = QLineEdit()
        self.game_path.setReadOnly(True)
        self.game_path.setText(self.config.game_directory or "")
        row.addWidget(self.game_path, stretch=1)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._choose_game_dir)
        row.addWidget(browse)
        self.mode_label = QLabel(_MODE_OFF_LABEL)
        self.mode_label.setStyleSheet("color: #f0d7a4;")
        self.mode_toggle = SlideToggle()
        self.mode_toggle.toggled.connect(self._on_mode_toggled)
        row.addWidget(self.mode_label)
        row.addWidget(self.mode_toggle)
        self._sync_mode_toggle()
        return row

    def _build_mods_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.mod_table = _table(["Name", "Version", "Author", "Files", "Archive"])
        self.mod_table.itemSelectionChanged.connect(self._update_uninstall_enabled)
        self.mod_table.cellDoubleClicked.connect(self._show_mod_files)
        layout.addWidget(self.mod_table)
        row = QHBoxLayout()
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.setEnabled(False)
        self.uninstall_button.clicked.connect(self._uninstall_selected)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_mods)
        row.addWidget(self.uninstall_button)
        row.addWidget(refresh)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_install_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.choose_archive_button = QPushButton("Choose archives")
        self.choose_archive_button.clicked.connect(self._choose_archives)
        clear_queue = QPushButton("Clear queue")
        clear_queue.clicked.connect(self._clear_install_queue)
        row.addWidget(self.choose_archive_button)
        row.addWidget(clear_queue)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel("Select one or more .zip / .rar files. They install one at a time.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.install_log = QPlainTextEdit()
        self.install_log.setReadOnly(True)
        layout.addWidget(self.install_log)
        return page

    def _build_infrastructure_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.health_table = _table(["Component", "File", "Status"])
        layout.addWidget(self.health_table)
        row = QHBoxLayout()
        scan = QPushButton("Scan")
        scan.clicked.connect(self._refresh_health)
        self.install_missing_button = QPushButton("Install missing infrastructure")
        self.install_missing_button.setEnabled(False)
        self.install_missing_button.clicked.connect(self._install_missing_infrastructure)
        deploy = QPushButton("Deploy local package")
        deploy.clicked.connect(self._deploy_local)
        self.dlsstweaks_button = QPushButton("Install DLSSTweaks (optional)")
        self.dlsstweaks_button.clicked.connect(self._install_dlsstweaks)
        row.addWidget(scan)
        row.addWidget(self.install_missing_button)
        row.addWidget(deploy)
        row.addWidget(self.dlsstweaks_button)
        row.addStretch(1)
        layout.addLayout(row)
        links = QHBoxLayout()
        for package in (*STANDARD_PACKAGES, *OPTIONAL_ADDONS):
            button = QPushButton(package.label)
            target = package.download_url or package.homepage
            button.clicked.connect(lambda _checked=False, url=target: webbrowser.open(url))
            links.addWidget(button)
        links.addStretch(1)
        layout.addLayout(links)
        self.infra_note = QPlainTextEdit()
        self.infra_note.setReadOnly(True)
        self.infra_note.setMaximumHeight(160)
        self.infra_note.setPlainText(
            "Install missing infrastructure will:\n"
            "- Auto-download Ultimate ASI Loader x64 and ScriptHookRDR2DotNet\n"
            "- For ScriptHookRDR2 V2 and Lenny's Mod Loader, show instructions first; "
            "you open the download page when ready, then select the archive\n"
            "RAR support is set up automatically (uses 7-Zip/UnRAR if present, otherwise "
            "downloads free UnRAR from rarlab.com). An existing lml folder is left in place.\n\n"
            "Optional: Install DLSSTweaks (also offered during infrastructure install) "
            "uses Nexus file \"1. DLSSTweaks for RDR2\" (xinput9_1_0.dll + dlsstweaks.ini + "
            "DLSSTweaksConfig.exe). After install you can open the config tool to enable "
            "ForceDLAA, then set in-game DLSS on and sharpening to 0."
        )
        layout.addWidget(self.infra_note)
        return page

    def _build_diagnostics_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.diagnostic_table = _table(["Severity", "Finding", "Suggestion"])
        self.diagnostic_table.itemSelectionChanged.connect(self._show_diagnostic_detail)
        layout.addWidget(self.diagnostic_table)
        scan = QPushButton("Scan crash log")
        scan.clicked.connect(lambda: self._refresh_diagnostics(popup=False))
        layout.addWidget(scan)
        self.diagnostic_detail = QPlainTextEdit()
        self.diagnostic_detail.setReadOnly(True)
        layout.addWidget(self.diagnostic_detail)
        return page

    def _startup(self) -> None:
        self._refresh_mods()
        game = self._game_dir(warn=False)
        if game is None:
            self.statusBar().showMessage("Select the RDR2 folder that contains RDR2.exe.")
            return
        self._refresh_health()
        self._refresh_diagnostics(popup=True)

    def _choose_game_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select the RDR2 folder")
        if not selected:
            return
        try:
            resolved = self.infrastructure.validate_game_directory(Path(selected))
        except CompanionError as exc:
            QMessageBox.warning(self, "RDR2 folder", str(exc))
            return
        self.config.game_directory = str(resolved)
        save_config(self.config)
        self.game_path.setText(str(resolved))
        self.statusBar().showMessage(f"Game folder set to {resolved}")
        statuses = self._refresh_health()
        self._refresh_diagnostics(popup=False)
        missing = self.infrastructure.missing_packages(statuses) if statuses else []
        if not missing:
            return
        listed = "\n".join(f"- {package.label}" for package in missing)
        answer = QMessageBox.question(
            self,
            "Install missing infrastructure",
            "This RDR2 folder is missing core modding files:\n"
            f"{listed}\n\nInstall the missing infrastructure now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._install_missing_infrastructure()

    def _choose_archives(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose mod archives",
            "",
            "Mod archives (*.zip *.rar)",
        )
        paths = [
            Path(item)
            for item in selected
            if Path(item).suffix.casefold() in {".zip", ".rar"}
        ]
        if not paths:
            return
        self._enqueue_installs(paths)

    def _clear_install_queue(self) -> None:
        if self._install_busy:
            QMessageBox.information(
                self,
                "Install queue",
                "The current archive will finish. Remaining queued archives were cleared.",
            )
        cleared = len(self._install_queue)
        self._install_queue.clear()
        if cleared:
            self._log(f"Cleared {cleared} queued archive(s).")
        self.statusBar().showMessage("Install queue cleared.")

    def _enqueue_installs(self, paths: list[Path]) -> None:
        self._install_queue.extend(paths)
        self._log(f"Queued {len(paths)} archive(s). Pending: {len(self._install_queue)}.")
        if not self._install_busy:
            self._install_results = []
            self._process_install_queue()

    def _process_install_queue(self) -> None:
        if not self._install_queue:
            self._install_busy = False
            self.choose_archive_button.setEnabled(True)
            self._refresh_mods()
            if self._install_results:
                installed = sum(1 for _name, status in self._install_results if status == "installed")
                cancelled = sum(1 for _name, status in self._install_results if status == "cancelled")
                failed = sum(1 for _name, status in self._install_results if status == "failed")
                summary = (
                    f"Queue finished: {installed} installed, "
                    f"{cancelled} cancelled, {failed} failed."
                )
                self._log(summary)
                self.statusBar().showMessage(summary)
            return

        self._install_busy = True
        self.choose_archive_button.setEnabled(False)
        archive = self._install_queue.pop(0)
        remaining = len(self._install_queue)
        self._log(f"--- Installing {archive.name} ({remaining} left in queue) ---")
        self.statusBar().showMessage(f"Installing {archive.name}…")
        status = self._install_archive(archive)
        self._install_results.append((archive.name, status))
        QTimer.singleShot(0, self._process_install_queue)

    def _install_archive(self, archive: Path) -> str:
        game = self._game_dir()
        if game is None:
            return "failed"
        staged = None
        found: list = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            staged = self.analyzer.stage(archive, game)
            found = self.collisions.detect(staged, self.manifests)
        except CompanionError as exc:
            failure: CompanionError | None = exc
        else:
            failure = None
        finally:
            QApplication.restoreOverrideCursor()
        if failure is not None:
            if staged is not None:
                self.analyzer.cleanup(staged)
            self._log(str(failure))
            QMessageBox.warning(self, "Install failed", str(failure))
            return "failed"
        if staged is None:
            return "failed"
        try:
            if staged.needs_placement_choice:
                if not self._resolve_manual_placement(staged):
                    self._log(f"Skipped {archive.name}.")
                    return "cancelled"
                found = self.collisions.detect(staged, self.manifests)
            if found and not self._resolve_collisions(staged, found):
                self._log(f"Skipped {archive.name}.")
                return "cancelled"
            written = self.analyzer.place(staged)
            try:
                self.manifests.save(
                    ModManifest(
                        mod_name=staged.metadata.name,
                        archive_source=archive.name,
                        files=[str(path) for path in written],
                        author=staged.metadata.author,
                        version=staged.metadata.version,
                    )
                )
            except CompanionError:
                for path in reversed(written):
                    path.unlink(missing_ok=True)
                raise
            self._log(f"Installed {staged.metadata.name} ({len(written)} files).")
            for warning in staged.warnings:
                self._log(f"Warning: {warning}")
            self.statusBar().showMessage(f"Installed {staged.metadata.name}")
            return "installed"
        except CompanionError as exc:
            self._log(str(exc))
            QMessageBox.warning(self, "Install failed", str(exc))
            return "failed"
        finally:
            self.analyzer.cleanup(staged)

    def _resolve_manual_placement(self, staged) -> bool:
        if staged.readme_path is not None and staged.readme_path.is_file():
            answer = QMessageBox.question(
                self,
                "Open readme?",
                f"{staged.metadata.name} includes {staged.readme_path.name}.\n\n"
                "Open it before choosing where to install?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(staged.readme_path)))

        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Manual mod install")
        dialog.setText(f"{staged.metadata.name} has no install.xml.")
        dialog.setInformativeText(
            "This usually means a root/manual mod rather than an LML package.\n\n"
            "Where should its files be installed?"
        )
        root_button = dialog.addButton("Game root", QMessageBox.ButtonRole.AcceptRole)
        lml_button = dialog.addButton("LML folder", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(root_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is root_button:
            mode = "root"
        elif clicked is lml_button:
            mode = "lml"
        else:
            return False
        try:
            self.analyzer.apply_placement(staged, mode)
        except CompanionError as exc:
            QMessageBox.warning(self, "Install failed", str(exc))
            return False
        self._log(f"Placement for {staged.metadata.name}: {mode}")
        return True

    def _resolve_collisions(self, staged, collisions) -> bool:
        foreign = [item for item in collisions if item.kind != REINSTALL]
        if foreign:
            QMessageBox.warning(
                self,
                "Collision",
                "Install stopped before any files were copied.\n\n"
                + "\n\n".join(item.message for item in foreign),
            )
            return False
        answer = QMessageBox.question(
            self,
            "Replace mod",
            f"{staged.metadata.name} is already installed. Replace it?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.manifests.uninstall(staged.metadata.name, staged.game_dir)
        return True

    def _uninstall_selected(self) -> None:
        mod_name = self._selected_mod()
        game = self._game_dir()
        if not mod_name or game is None:
            return
        answer = QMessageBox.question(self, "Uninstall", f"Remove {mod_name} and its tracked files?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.manifests.uninstall(mod_name, game)
        except CompanionError as exc:
            QMessageBox.warning(self, "Uninstall failed", str(exc))
            return
        self.statusBar().showMessage(f"Removed {len(result.removed_files)} files for {mod_name}.")
        self._refresh_mods()

    def _show_mod_files(self, row: int, _column: int) -> None:
        item = self.mod_table.item(row, 0)
        if item is None:
            return
        mod_name = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(mod_name, str) or not mod_name:
            return
        try:
            manifest = self.manifests.load(mod_name)
        except CompanionError as exc:
            QMessageBox.warning(self, "Mod files", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(manifest.mod_name)
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                f"{manifest.mod_name}\n"
                f"Version {manifest.version} · {manifest.author}\n"
                f"{len(manifest.files)} tracked file(s) · Archive: {manifest.archive_source}"
            )
        )
        files = QPlainTextEdit()
        files.setReadOnly(True)
        files.setPlainText("\n".join(manifest.files) if manifest.files else "(no tracked files)")
        layout.addWidget(files)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _deploy_local(self) -> None:
        game = self._game_dir()
        if game is None:
            return
        choice = QMessageBox(self)
        choice.setWindowTitle("Deploy package")
        choice.setText(
            "Choose a downloaded ScriptHookRDR2 V2, Ultimate ASI Loader x64, "
            "Lenny's Mod Loader, or ScriptHookRDR2DotNet package."
        )
        archive_button = choice.addButton("Archive", QMessageBox.ButtonRole.AcceptRole)
        folder_button = choice.addButton("Folder", QMessageBox.ButtonRole.AcceptRole)
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()
        clicked = choice.clickedButton()
        if clicked is archive_button:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Deploy a ScriptHookRDR2 V2 or LML package",
                "",
                "Packages (*.zip *.rar)",
            )
            source = Path(selected) if selected else None
        elif clicked is folder_button:
            selected = QFileDialog.getExistingDirectory(self, "Select an extracted package folder")
            source = Path(selected) if selected else None
        else:
            source = None
        if source is None:
            return
        try:
            result = self.infrastructure.deploy_local(source, game)
        except CompanionError as exc:
            QMessageBox.warning(self, "Deploy failed", str(exc))
            return
        names = ", ".join(path.name for path in result.copied) or "nothing new"
        notes = " ".join(result.notes)
        self.statusBar().showMessage(f"Deployed {names}. {notes}".strip())
        self._refresh_health()

    def _install_dlsstweaks(self) -> None:
        game = self._game_dir()
        if game is None:
            return
        package = DLSS_TWEAKS_PACKAGE
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(package.label)
        dialog.setText("Install DLSSTweaks for RDR2 (optional).")
        dialog.setInformativeText(
            "1. Click Open download page and get file "
            "\"1. DLSSTweaks for RDR2\".\n"
            "2. Come back and click Select downloaded file.\n"
            "3. Files are copied next to RDR2.exe; you can then open DLSSTweaksConfig.\n"
            "Skip cancels without changing anything."
        )
        open_button = dialog.addButton(
            "Open download page",
            QMessageBox.ButtonRole.ActionRole,
        )
        select_button = dialog.addButton(
            "Select downloaded file",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(open_button)

        selected: Path | None = None
        while True:
            self.raise_()
            self.activateWindow()
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked is open_button:
                webbrowser.open(package.homepage)
                self.raise_()
                self.activateWindow()
                continue
            if clicked is select_button:
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    f"Select {package.label}",
                    "",
                    "Packages (*.zip *.rar);;All files (*.*)",
                )
                if path:
                    selected = Path(path)
                    break
                continue
            return

        try:
            result = self.infrastructure.install_dlsstweaks(game, selected)
        except CompanionError as exc:
            QMessageBox.warning(self, package.label, str(exc))
            return
        names = ", ".join(path.name for path in result.copied) or "no new files"
        notes = " ".join(result.notes)
        summary = f"DLSSTweaks: {names}. {notes}".strip()
        self.infra_note.appendPlainText(summary)
        self.statusBar().showMessage(summary)
        self._refresh_health()
        self._guide_dlsstweaks_config(game)

    def _guide_dlsstweaks_config(self, game: Path) -> None:
        config_exe = game / "DLSSTweaksConfig.exe"
        if not config_exe.is_file():
            QMessageBox.information(
                self,
                DLSS_TWEAKS_PACKAGE.label,
                "DLSSTweaksConfig.exe was not found in the package.\n\n"
                "Edit dlsstweaks.ini manually and set ForceDLAA = true if you want native DLAA.",
            )
            self._remind_dlsstweaks_ingame()
            return

        ask = QMessageBox.question(
            self,
            DLSS_TWEAKS_PACKAGE.label,
            "Open DLSSTweaksConfig to set your preferred options?\n\n"
            "Recommended: set ForceDLAA to True, then Save.",
        )
        if ask != QMessageBox.StandardButton.Yes:
            self._remind_dlsstweaks_ingame()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Configure DLSSTweaks")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        instructions = QLabel(
            "In DLSSTweaksConfig:\n"
            "1. Set ForceDLAA to True (forces native DLAA for all DLSS modes).\n"
            "2. Adjust any other presets you want.\n"
            "3. Save the config, then close DLSSTweaksConfig.\n"
            "4. Click Done here when finished."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        row = QHBoxLayout()
        open_button = QPushButton("Open DLSSTweaksConfig")
        done_button = QPushButton("Done")
        row.addWidget(open_button)
        row.addStretch(1)
        row.addWidget(done_button)
        layout.addLayout(row)

        def open_config() -> None:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_exe))):
                QMessageBox.warning(
                    dialog,
                    DLSS_TWEAKS_PACKAGE.label,
                    f"Could not open:\n{config_exe}",
                )

        open_button.clicked.connect(open_config)
        done_button.clicked.connect(dialog.accept)
        dialog.exec()
        self._remind_dlsstweaks_ingame()

    def _remind_dlsstweaks_ingame(self) -> None:
        QMessageBox.information(
            self,
            "In-game graphics settings",
            "In RDR2 after launch:\n"
            "1. Open Settings > Graphics.\n"
            "2. Enable NVIDIA DLSS.\n"
            "3. Set the in-game sharpening slider to 0 "
            "(DLSSTweaks handles clarity through its config).\n\n"
            "A dlsstweaks.log in the game folder means the hook loaded.",
        )

    def _ask_offer_dlsstweaks(self, game: Path) -> bool:
        try:
            if self.infrastructure.dlsstweaks_installed(game):
                return False
        except CompanionError:
            return False
        return (
            QMessageBox.question(
                self,
                DLSS_TWEAKS_PACKAGE.label,
                "Also install optional DLSSTweaks for RDR2?\n\n"
                "Uses Nexus file \"1. DLSSTweaks for RDR2\" (xinput9_1_0.dll). "
                "You can skip and install it later from the Infrastructure tab.",
            )
            == QMessageBox.StandardButton.Yes
        )

    def _install_missing_infrastructure(self) -> None:
        game = self._game_dir()
        if game is None:
            return
        if self._infra_thread is not None and self._infra_thread.isRunning():
            QMessageBox.information(
                self,
                "Infrastructure",
                "An infrastructure install is already running.",
            )
            return
        missing = self.infrastructure.missing_packages(game_dir=game)
        self._offer_dlss_after_infra = self._ask_offer_dlsstweaks(game)
        if not missing:
            self.statusBar().showMessage("All standard infrastructure files are already present.")
            self._refresh_health()
            if self._offer_dlss_after_infra:
                self._offer_dlss_after_infra = False
                self._install_dlsstweaks()
            return
        self.tabs.setCurrentIndex(2)
        self.install_missing_button.setEnabled(False)
        self.infra_note.appendPlainText("\nStarting infrastructure install...")
        thread = QThread(self)
        worker = InstallMissingWorker(self.infrastructure, game)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_infra_progress)
        worker.need_manual.connect(self._on_infra_manual_needed)
        worker.finished.connect(self._on_infra_finished)
        worker.failed.connect(self._on_infra_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_infra_thread_finished)
        self._infra_thread = thread
        self._infra_worker = worker
        thread.start()

    def _on_infra_progress(self, message: str) -> None:
        self.infra_note.appendPlainText(message)
        self.statusBar().showMessage(message)

    def _on_infra_manual_needed(self, request: object) -> None:
        if not isinstance(request, _ManualPackageRequest):
            return
        self._pending_manual = request
        try:
            request.path = self._prompt_manual_package(request.package)
        finally:
            request.event.set()
            if self._pending_manual is request:
                self._pending_manual = None

    def _prompt_manual_package(self, package: PackageSource) -> Path | None:
        """Keep the app in front: open the site only when the user asks, then pick the file."""
        expected = package.expected_archive or "the package archive"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(package.label)
        dialog.setText(f"{package.label} needs a manual download.")
        dialog.setInformativeText(
            f"1. Click Open download page and save {expected}.\n"
            "2. Come back here and click Select downloaded file.\n"
            "3. Or click Skip to continue without this package."
        )
        open_button = dialog.addButton(
            "Open download page",
            QMessageBox.ButtonRole.ActionRole,
        )
        select_button = dialog.addButton(
            "Select downloaded file",
            QMessageBox.ButtonRole.AcceptRole,
        )
        dialog.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(open_button)

        while True:
            self.raise_()
            self.activateWindow()
            dialog.raise_()
            dialog.activateWindow()
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked is open_button:
                webbrowser.open(package.homepage)
                self.raise_()
                self.activateWindow()
                continue
            if clicked is select_button:
                selected, _ = QFileDialog.getOpenFileName(
                    self,
                    f"Select {package.label}",
                    "",
                    "Packages (*.zip *.rar);;All files (*.*)",
                )
                if selected:
                    return Path(selected)
                # File dialog cancelled — show the instructions again.
                continue
            return None

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._pending_manual is not None and not self._pending_manual.event.is_set():
            self._pending_manual.path = None
            self._pending_manual.event.set()
        if self._infra_thread is not None and self._infra_thread.isRunning():
            self._infra_thread.quit()
            self._infra_thread.wait(5000)
        super().closeEvent(event)

    def _on_infra_finished(self, result: object) -> None:
        if not isinstance(result, InstallMissingResult):
            return
        self.infra_note.appendPlainText("\n" + result.short_summary())
        if result.failed:
            self.infra_note.appendPlainText(result.detail_summary())
        self._refresh_health()
        offer_dlss = self._offer_dlss_after_infra
        self._offer_dlss_after_infra = False
        if not result.outcomes:
            self.statusBar().showMessage("All standard infrastructure files are already present.")
            if offer_dlss:
                self._install_dlsstweaks()
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Infrastructure")
        dialog.setText(self._infra_result_headline(result))
        dialog.setInformativeText(result.short_summary())
        dialog.setDetailedText(result.detail_summary())
        if result.failed and not result.deployed:
            dialog.setIcon(QMessageBox.Icon.Warning)
            self.statusBar().showMessage("Infrastructure install failed.")
        elif result.failed:
            dialog.setIcon(QMessageBox.Icon.Warning)
            self.statusBar().showMessage("Infrastructure install finished with some failures.")
        else:
            dialog.setIcon(QMessageBox.Icon.Information)
            self.statusBar().showMessage("Infrastructure install finished.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
        if offer_dlss:
            self._install_dlsstweaks()

    def _infra_result_headline(self, result: InstallMissingResult) -> str:
        deployed = len(result.deployed)
        failed = len(result.failed)
        skipped = len(result.skipped)
        if failed and not deployed:
            return "Infrastructure install failed."
        if failed:
            return (
                f"Installed {deployed} package(s), but {failed} failed"
                + (f" and {skipped} skipped." if skipped else ".")
            )
        if skipped and deployed:
            return f"Installed {deployed} package(s); {skipped} skipped."
        if skipped and not deployed:
            return "No packages were installed."
        return f"Successfully installed {deployed} package(s)."

    def _on_infra_failed(self, message: str) -> None:
        self.infra_note.appendPlainText(message)
        self._refresh_health()
        QMessageBox.warning(self, "Infrastructure", message)
        if self._offer_dlss_after_infra:
            self._offer_dlss_after_infra = False
            self._install_dlsstweaks()

    def _on_infra_thread_finished(self) -> None:
        self._infra_thread = None
        self._infra_worker = None
        self._refresh_health()

    def _on_mode_toggled(self, checked: bool) -> None:
        target = Profile.VANILLA_ONLINE if checked else Profile.MODDED_STORY
        game = self._game_dir(warn=False)
        if game is None:
            QMessageBox.information(
                self,
                "RDR2 folder",
                "Select the RDR2 folder that contains RDR2.exe before switching modes.",
            )
            self._sync_mode_toggle()
            return
        if checked:
            answer = QMessageBox.question(
                self,
                _MODE_ON_LABEL,
                "Disable mods for online play?\n\n"
                "This renames dinput8.dll, root .asi plugins, and DLSSTweaks injectors "
                "(xinput9_1_0.dll / nvngx.dll) with a .off suffix. "
                "Files under lml stay on disk.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._sync_mode_toggle()
                return
        try:
            report = self.profiles.switch(game, target)
        except CompanionError as exc:
            QMessageBox.warning(self, "Mode switch", str(exc))
            self._sync_mode_toggle()
            return
        self.config.active_profile = target.value
        save_config(self.config)
        self._sync_mode_toggle()
        self._refresh_health()
        self.statusBar().showMessage(report.summary().splitlines()[0])

    def _sync_mode_toggle(self) -> None:
        try:
            profile = Profile(self.config.active_profile)
        except ValueError:
            profile = self.profiles.current()
        online = profile is not Profile.MODDED_STORY
        self.mode_toggle.blockSignals(True)
        self.mode_toggle.setChecked(online, animate=False)
        self.mode_toggle.blockSignals(False)
        self.mode_label.setText(_MODE_ON_LABEL if online else _MODE_OFF_LABEL)
        if self.hero_banner is not None:
            self.hero_banner.set_online_mode(online)

    def _refresh_mods(self) -> None:
        try:
            manifests = self.manifests.list_manifests()
        except CompanionError as exc:
            QMessageBox.warning(self, "Mod library", str(exc))
            return
        self.mod_table.setRowCount(len(manifests))
        for row, manifest in enumerate(manifests):
            values = [
                manifest.mod_name,
                manifest.version,
                manifest.author,
                str(len(manifest.files)),
                manifest.archive_source,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, manifest.mod_name)
                self.mod_table.setItem(row, column, item)
        self._update_uninstall_enabled()

    def _refresh_health(self):
        game = self._game_dir(warn=False)
        self.health_table.setRowCount(0)
        if game is None:
            self.install_missing_button.setEnabled(False)
            return None
        try:
            statuses = self.infrastructure.health_check(game)
        except CompanionError as exc:
            QMessageBox.warning(self, "Infrastructure", str(exc))
            self.install_missing_button.setEnabled(False)
            return None
        self.health_table.setRowCount(len(statuses))
        for row, status in enumerate(statuses):
            label = QTableWidgetItem(status.label)
            filename = QTableWidgetItem(status.filename)
            state = QTableWidgetItem(status.state)
            color = _STATE_COLORS.get(status.state)
            if color is not None:
                state.setForeground(QBrush(color))
            self.health_table.setItem(row, 0, label)
            self.health_table.setItem(row, 1, filename)
            self.health_table.setItem(row, 2, state)
        busy = self._infra_thread is not None and self._infra_thread.isRunning()
        missing = self.infrastructure.missing_packages(statuses)
        self.install_missing_button.setEnabled(bool(missing) and not busy)
        return statuses

    def _refresh_diagnostics(self, popup: bool) -> None:
        game = self._game_dir(warn=False)
        self._diagnostic_findings = []
        self.diagnostic_table.setRowCount(0)
        self.diagnostic_detail.clear()
        if game is None:
            return
        findings = self.diagnostics.inspect(game)
        self._diagnostic_findings = findings
        self.diagnostic_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            self.diagnostic_table.setItem(row, 0, QTableWidgetItem(finding.severity))
            self.diagnostic_table.setItem(row, 1, QTableWidgetItem(finding.title))
            self.diagnostic_table.setItem(row, 2, QTableWidgetItem(finding.suggestion))
        warnings = [item for item in findings if item.severity == "warning"]
        if popup and warnings:
            text = "\n\n".join(f"{item.title}\n{item.suggestion}" for item in warnings)
            QMessageBox.warning(self, "Crash log", text)

    def _show_diagnostic_detail(self) -> None:
        row = self.diagnostic_table.currentRow()
        findings = getattr(self, "_diagnostic_findings", [])
        if row < 0 or row >= len(findings):
            return
        finding = findings[row]
        location = str(finding.log_path) if finding.log_path else "No log path"
        self.diagnostic_detail.setPlainText(
            f"{finding.title}\n{location}\n\n{finding.detail}\n\n{finding.suggestion}"
        )

    def _game_dir(self, warn: bool = True) -> Path | None:
        raw = self.config.game_directory
        if not raw:
            if warn:
                QMessageBox.information(
                    self,
                    "RDR2 folder",
                    "Select the RDR2 folder that contains RDR2.exe.",
                )
            return None
        try:
            return self.infrastructure.validate_game_directory(Path(raw))
        except CompanionError as exc:
            if warn:
                QMessageBox.warning(self, "RDR2 folder", str(exc))
            return None

    def _selected_mod(self) -> str | None:
        row = self.mod_table.currentRow()
        if row < 0:
            return None
        item = self.mod_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def _update_uninstall_enabled(self) -> None:
        self.uninstall_button.setEnabled(self._selected_mod() is not None)

    def _log(self, message: str) -> None:
        self.install_log.appendPlainText(message)


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header.setStretchLastSection(True)
    return table
