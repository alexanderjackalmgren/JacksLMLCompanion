"""Main window: mod library, installer, infrastructure, diagnostics, and profiles."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import CompanionError
from core.analyzer import ModAnalyzer
from core.collision import REINSTALL, CollisionDetector
from core.diagnostics import CrashDiagnostics
from core.infrastructure import (
    STANDARD_PACKAGES,
    AppConfig,
    InfrastructureManager,
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
#dropArea { border: 1px dashed #6b5840; background: #141311; }
"""

_PROFILE_COPY = {
    Profile.MODDED_STORY: (
        "Story mode with ScriptHookRDR2 V2, the ASI loader, and Lenny's Mod Loader active."
    ),
    Profile.VANILLA_ONLINE: (
        "Quarantines dinput8.dll and root .asi plugins by renaming them with a .off suffix. "
        "Mod files under lml stay on disk and are not deleted."
    ),
    Profile.REDM: (
        "Quarantines single-player script loaders the same way Vanilla Online does. "
        "Point RedM at this game folder; automatic client linking is not wired up yet."
    ),
}

_STATE_COLORS = {
    "present": QColor("#b7d3b0"),
    "quarantined": QColor("#e6c98a"),
    "missing": QColor("#e0a090"),
}


class DropArea(QFrame):
    def __init__(self, on_archive) -> None:
        super().__init__()
        self._on_archive = on_archive
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setMinimumHeight(96)
        layout = QVBoxLayout(self)
        label = QLabel("Drop a .zip or .rar mod here")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.casefold() in {".zip", ".rar"}:
                self._on_archive(path)
                return
        QMessageBox.information(self, "Unsupported file", "Drop a .zip or .rar archive.")


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
        self.resize(1080, 720)
        self.setStyleSheet(_STYLE)
        self.setStatusBar(QStatusBar())
        self._build()
        QTimer.singleShot(0, self._startup)

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_mods_tab(), "Mods")
        self.tabs.addTab(self._build_install_tab(), "Install")
        self.tabs.addTab(self._build_infrastructure_tab(), "Infrastructure")
        self.tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        self.tabs.addTab(self._build_profiles_tab(), "Profiles")
        layout.addWidget(self.tabs)

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
        self.profile_label = QLabel()
        row.addWidget(self.profile_label)
        self._sync_profile_label()
        return row

    def _build_mods_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.mod_table = _table(["Name", "Version", "Author", "Files", "Archive"])
        self.mod_table.itemSelectionChanged.connect(self._update_uninstall_enabled)
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
        layout.addWidget(DropArea(self._install_archive))
        browse = QPushButton("Choose archive")
        browse.clicked.connect(self._choose_archive)
        layout.addWidget(browse)
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
        deploy = QPushButton("Deploy local package")
        deploy.clicked.connect(self._deploy_local)
        row.addWidget(scan)
        row.addWidget(deploy)
        row.addStretch(1)
        layout.addLayout(row)
        links = QHBoxLayout()
        for package in STANDARD_PACKAGES:
            button = QPushButton(package.label)
            target = package.download_url or package.homepage
            button.clicked.connect(lambda _checked=False, url=target: webbrowser.open(url))
            links.addWidget(button)
        links.addStretch(1)
        layout.addLayout(links)
        note = QPlainTextEdit()
        note.setReadOnly(True)
        note.setMaximumHeight(140)
        note.setPlainText(
            "Automatic downloads are not enabled. Standard stack:\n"
            "1. ScriptHookRDR2 V2 (kepmehz)\n"
            "2. Ultimate ASI Loader x64 dinput8.dll (ThirteenAG)\n"
            "3. Lenny's Mod Loader RDR (lml_rdr_beta_11.zip from rdr2mods.com)\n"
            "4. ScriptHookRDR2DotNet 1.0.5.5\n"
            "Download each package, then deploy the archive or folder here. "
            "An existing lml folder is left in place."
        )
        layout.addWidget(note)
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

    def _build_profiles_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.profile_buttons = QButtonGroup(self)
        self._profile_lookup: dict[int, Profile] = {}
        for index, profile in enumerate(Profile):
            button = QRadioButton(profile.label)
            self.profile_buttons.addButton(button, index)
            self._profile_lookup[index] = profile
            layout.addWidget(button)
            button.toggled.connect(self._update_profile_copy)
        self.profile_copy = QLabel()
        self.profile_copy.setWordWrap(True)
        layout.addWidget(self.profile_copy)
        apply_button = QPushButton("Apply profile")
        apply_button.clicked.connect(self._apply_profile)
        layout.addWidget(apply_button)
        self.profile_log = QPlainTextEdit()
        self.profile_log.setReadOnly(True)
        layout.addWidget(self.profile_log)
        self._select_profile(self.profiles.current())
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
        self._refresh_health()
        self._refresh_diagnostics(popup=False)

    def _choose_archive(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a mod archive",
            "",
            "Mod archives (*.zip *.rar)",
        )
        if selected:
            self._install_archive(Path(selected))

    def _install_archive(self, archive: Path) -> None:
        game = self._game_dir()
        if game is None:
            return
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
            return
        if staged is None:
            return
        try:
            if found and not self._resolve_collisions(staged, found):
                self._log("Install cancelled.")
                return
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
            self._refresh_mods()
            self.statusBar().showMessage(f"Installed {staged.metadata.name}")
        except CompanionError as exc:
            self._log(str(exc))
            QMessageBox.warning(self, "Install failed", str(exc))
        finally:
            self.analyzer.cleanup(staged)

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

    def _apply_profile(self) -> None:
        game = self._game_dir()
        profile = self._selected_profile()
        if game is None or profile is None:
            return
        if profile is not Profile.MODDED_STORY:
            answer = QMessageBox.question(
                self,
                profile.label,
                f"Quarantine ASI loaders and root .asi plugins for {profile.label}?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            report = self.profiles.switch(game, profile)
        except CompanionError as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return
        self.config.active_profile = profile.value
        save_config(self.config)
        self._sync_profile_label()
        self.profile_log.setPlainText(report.summary())
        self._refresh_health()
        self.statusBar().showMessage(f"Active profile: {profile.label}")

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

    def _refresh_health(self) -> None:
        game = self._game_dir(warn=False)
        self.health_table.setRowCount(0)
        if game is None:
            return
        try:
            statuses = self.infrastructure.health_check(game)
        except CompanionError as exc:
            QMessageBox.warning(self, "Infrastructure", str(exc))
            return
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

    def _selected_profile(self) -> Profile | None:
        button_id = self.profile_buttons.checkedId()
        return self._profile_lookup.get(button_id)

    def _select_profile(self, profile: Profile) -> None:
        for button_id, candidate in self._profile_lookup.items():
            if candidate is profile:
                button = self.profile_buttons.button(button_id)
                if button is not None:
                    button.setChecked(True)
                return

    def _update_profile_copy(self) -> None:
        profile = self._selected_profile()
        self.profile_copy.setText(_PROFILE_COPY.get(profile, "") if profile else "")

    def _sync_profile_label(self) -> None:
        try:
            profile = Profile(self.config.active_profile)
        except ValueError:
            profile = self.profiles.current()
        self.profile_label.setText(profile.label)

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
