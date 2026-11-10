"""Core tests for routing, collisions, uninstall, and profile quarantine."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from core import CompanionError
from core.analyzer import ArchiveError, ModAnalyzer, PlannedFile, StagedInstall
from core.collision import REINSTALL, ROOT_OVERWRITE, LML_FOLDER, CollisionDetector
from core.diagnostics import CrashDiagnostics
from core.infrastructure import (
    ASI_LOADER_DOWNLOAD,
    ASI_LOADER_LABEL,
    DOTNET_DOWNLOAD,
    DOTNET_VERSION,
    LML_PACKAGE_NAME,
    SCRIPT_HOOK_LABEL,
    SCRIPT_HOOK_PAGE,
    STANDARD_PACKAGES,
    AppConfig,
    InfrastructureError,
    InfrastructureManager,
    load_config,
    save_config,
)
from core.manifest import ManifestError, ManifestStore, ModManifest
from core.profiles import Profile, ProfileSwitcher


def make_zip(path: Path, entries: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)


class GameSandbox(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.game = self.root / "game"
        self.game.mkdir()
        (self.game / "RDR2.exe").write_bytes(b"exe")
        self.analyzer = ModAnalyzer(staging_root=self.root / "staging")
        self.store = ManifestStore(self.root / "manifests")
        self.collisions = CollisionDetector()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_routes_root_scripts_and_lml_assets(self) -> None:
        archive = self.root / "cool_mod.zip"
        make_zip(archive, {"Cool.asi": "asi", "stuff/model.ytd": "ytd", "readme.txt": "hi"})
        staged = self.analyzer.stage(archive, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged))
        destinations = {item.relative_destination.as_posix() for item in staged.files}
        self.assertEqual(
            destinations,
            {
                "Cool.asi",
                "lml/cool_mod/stuff/model.ytd",
                "lml/cool_mod/readme.txt",
                "lml/cool_mod/install.xml",
            },
        )
        self.assertTrue(staged.metadata.generated)
        kinds = {item.relative_destination.as_posix(): item.kind for item in staged.files}
        self.assertEqual(kinds["Cool.asi"], "root")
        self.assertEqual(kinds["lml/cool_mod/stuff/model.ytd"], "lml")

    def test_install_xml_keeps_game_paths_inside_the_mod_folder(self) -> None:
        archive = self.root / "pack.zip"
        install_xml = """<?xml version="1.0" encoding="utf-8"?>
<package>
  <metadata>
    <name>Pretty Mod</name>
    <author>Ada</author>
    <version>1.2.3</version>
  </metadata>
  <files>
    <file>
      <source>plugin.asi</source>
      <destination>plugin.asi</destination>
    </file>
    <file>
      <source>data/file.ymt</source>
      <destination>x64/data/file.ymt</destination>
    </file>
  </files>
</package>
"""
        make_zip(
            archive,
            {
                "install.xml": install_xml,
                "plugin.asi": "asi",
                "data/file.ymt": "ymt",
                "readme.txt": "hi",
            },
        )
        staged = self.analyzer.stage(archive, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged))
        self.assertEqual(staged.metadata.name, "Pretty Mod")
        self.assertEqual(staged.metadata.author, "Ada")
        self.assertEqual(staged.metadata.version, "1.2.3")
        self.assertFalse(staged.metadata.generated)
        destinations = {item.relative_destination.as_posix() for item in staged.files}
        self.assertIn("plugin.asi", destinations)
        self.assertIn("lml/Pretty Mod/x64/data/file.ymt", destinations)
        self.assertNotIn("x64/data/file.ymt", destinations)
        self.assertIn("lml/Pretty Mod/readme.txt", destinations)

    def test_rejects_zip_slip_and_root_game_executable(self) -> None:
        slipped = self.root / "slipped.zip"
        make_zip(slipped, {"../escaped.txt": "nope"})
        with self.assertRaises(ArchiveError):
            self.analyzer.stage(slipped, self.game)
        self.assertFalse((self.root / "escaped.txt").exists())
        self.assertFalse((self.root / "staging" / "escaped.txt").exists())

        replacement = self.root / "replacement.zip"
        make_zip(replacement, {"RDR2.exe": b"replaced"})
        staged = self.analyzer.stage(replacement, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged))
        destinations = {item.relative_destination.as_posix() for item in staged.files}
        self.assertNotIn("RDR2.exe", destinations)
        self.assertIn("lml/replacement/RDR2.exe", destinations)
        self.assertEqual((self.game / "RDR2.exe").read_bytes(), b"exe")

    def test_install_xml_cannot_redirect_a_dll_onto_rdr2(self) -> None:
        archive = self.root / "hook.zip"
        install_xml = """<easy><name>Hook</name>
        <file><source>hook.dll</source><destination>RDR2.exe</destination></file>
        </easy>"""
        make_zip(archive, {"install.xml": install_xml, "hook.dll": b"dll"})
        staged = self.analyzer.stage(archive, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged))
        with self.assertRaises(ArchiveError):
            self.analyzer.place(staged)
        self.assertEqual((self.game / "RDR2.exe").read_bytes(), b"exe")

    def test_place_rolls_back_when_a_path_escapes_the_game_folder(self) -> None:
        staging = self.root / "staging" / "tmp_extract_manual"
        staging.mkdir(parents=True)
        source = staging / "ok.txt"
        source.write_text("ok", encoding="utf-8")
        bad = staging / "bad.txt"
        bad.write_text("bad", encoding="utf-8")
        staged = StagedInstall(
            metadata=self.analyzer.stage(self._tiny_archive("safe"), self.game).metadata,
            archive_source=self.root / "safe.zip",
            staging_dir=staging,
            game_dir=self.game,
            files=[
                PlannedFile(source, Path("lml") / "Mod" / "ok.txt", "lml"),
                PlannedFile(bad, Path("..") / "escaped.txt", "lml"),
            ],
        )
        with self.assertRaises(CompanionError):
            self.analyzer.place(staged)
        self.assertFalse((self.game / "lml" / "Mod" / "ok.txt").exists())
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_collision_reinstall_and_foreign_files(self) -> None:
        archive = self._tiny_archive("cool_mod")
        staged = self._install(archive)
        again = self.analyzer.stage(archive, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(again))
        collisions = self.collisions.detect(again, self.store)
        self.assertEqual([item.kind for item in collisions], [REINSTALL])

        (self.game / "Cool.asi").write_text("owned", encoding="utf-8")
        self.store.save(
            ModManifest(
                mod_name="Other",
                archive_source="other.zip",
                files=[str(self.game / "Cool.asi")],
            )
        )
        incoming = self.root / "incoming.zip"
        make_zip(incoming, {"Cool.asi": "new"})
        staged_incoming = self.analyzer.stage(incoming, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged_incoming))
        foreign = self.collisions.detect(staged_incoming, self.store)
        self.assertTrue(any(item.kind == ROOT_OVERWRITE and item.existing_mod == "Other" for item in foreign))
        self.assertIsNotNone(staged)

    def test_collision_on_existing_lml_folder(self) -> None:
        (self.game / "lml" / "cool_mod").mkdir(parents=True)
        archive = self.root / "cool_mod.zip"
        make_zip(archive, {"stuff/model.ytd": "ytd"})
        staged = self.analyzer.stage(archive, self.game)
        self.addCleanup(lambda: self.analyzer.cleanup(staged))
        collisions = self.collisions.detect(staged, self.store)
        self.assertTrue(any(item.kind == LML_FOLDER for item in collisions))

    def test_uninstall_removes_tracked_files_and_empty_folders(self) -> None:
        archive = self._tiny_archive("cool_mod")
        staged = self._install(archive)
        kept = self.game / "lml" / "other"
        kept.mkdir()
        (kept / "keep.txt").write_text("keep", encoding="utf-8")
        result = self.store.uninstall(staged.metadata.name, self.game)
        self.assertTrue(result.removed_files)
        self.assertFalse((self.game / "lml" / staged.metadata.name).exists())
        self.assertFalse((self.game / "Cool.asi").exists())
        self.assertTrue((self.game / "lml").is_dir())
        self.assertTrue((kept / "keep.txt").is_file())
        self.assertEqual((self.game / "RDR2.exe").read_bytes(), b"exe")
        self.assertEqual(self.store.list_manifests(), [])

    def test_uninstall_stops_before_deleting_protected_or_outside_paths(self) -> None:
        mod_file = self.game / "lml" / "Bad" / "a.txt"
        mod_file.parent.mkdir(parents=True)
        mod_file.write_text("mod", encoding="utf-8")
        outside = self.root / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        self.store.save(
            ModManifest(
                mod_name="Bad",
                archive_source="bad.zip",
                files=[str(mod_file), str(outside), str(self.game / "RDR2.exe")],
            )
        )
        with self.assertRaises(ManifestError):
            self.store.uninstall("Bad", self.game)
        self.assertTrue(outside.is_file())
        self.assertTrue(mod_file.is_file())
        self.assertEqual((self.game / "RDR2.exe").read_bytes(), b"exe")
        self.assertEqual(self.store.load("Bad").mod_name, "Bad")

    def test_profile_quarantine_restores_and_leaves_mods_in_place(self) -> None:
        (self.game / "DInput8.dll").write_bytes(b"loader")
        (self.game / "VFS.asi").write_bytes(b"vfs")
        (self.game / "NativeTrainer.asi").write_bytes(b"trainer")
        (self.game / "ScriptHookRDR2.dll").write_bytes(b"hook")
        (self.game / "version.dll").write_bytes(b"game")
        (self.game / "notes.txt").write_text("notes", encoding="utf-8")
        mod_file = self.game / "lml" / "mod" / "a.txt"
        mod_file.parent.mkdir(parents=True)
        mod_file.write_text("mod", encoding="utf-8")
        switcher = ProfileSwitcher(self.root / "profile_state.json")

        online = switcher.switch(self.game, Profile.VANILLA_ONLINE)
        self.assertIn("lml/", online.summary())
        self.assertTrue((self.game / "DInput8.dll.off").is_file())
        self.assertTrue((self.game / "VFS.asi.off").is_file())
        self.assertTrue((self.game / "NativeTrainer.asi.off").is_file())
        self.assertFalse((self.game / "DInput8.dll").exists())
        self.assertFalse((self.game / "VFS.asi").exists())
        self.assertEqual((self.game / "ScriptHookRDR2.dll").read_bytes(), b"hook")
        self.assertEqual((self.game / "version.dll").read_bytes(), b"game")
        self.assertEqual(mod_file.read_text(encoding="utf-8"), "mod")
        self.assertEqual(switcher.current(), Profile.VANILLA_ONLINE)

        switcher.switch(self.game, Profile.MODDED_STORY)
        self.assertTrue((self.game / "DInput8.dll").is_file())
        self.assertTrue((self.game / "VFS.asi").is_file())
        self.assertTrue((self.game / "NativeTrainer.asi").is_file())
        self.assertFalse((self.game / "VFS.asi.off").exists())
        self.assertEqual(switcher.current(), Profile.MODDED_STORY)

        (self.game / "VFS.asi.off").write_bytes(b"parked")
        with self.assertRaises(CompanionError):
            switcher.switch(self.game, Profile.REDM)
        self.assertTrue((self.game / "VFS.asi").is_file())
        self.assertTrue((self.game / "VFS.asi.off").is_file())
        self.assertTrue((self.game / "DInput8.dll").is_file())
        self.assertEqual(switcher.current(), Profile.MODDED_STORY)

    def test_deploy_prefers_x64_dinput8_and_rejects_win32_only(self) -> None:
        package = self.root / "loaders"
        (package / "Win32").mkdir(parents=True)
        (package / "x64").mkdir(parents=True)
        (package / "Win32" / "dinput8.dll").write_bytes(b"win32-loader")
        (package / "x64" / "dinput8.dll").write_bytes(b"x64-loader")
        manager = InfrastructureManager()
        result = manager.deploy_local(package, self.game)
        self.assertEqual((self.game / "dinput8.dll").read_bytes(), b"x64-loader")
        self.assertTrue(any("x64 ASI loader" in note for note in result.notes))

        alias_package = self.root / "alias"
        alias_package.mkdir()
        (alias_package / "dinput8-x64.dll").write_bytes(b"alias-loader")
        manager.deploy_local(alias_package, self.game)
        self.assertEqual((self.game / "dinput8.dll").read_bytes(), b"alias-loader")
        self.assertFalse((self.game / "dinput8-x64.dll").exists())

        dotnet_package = self.root / "dotnet"
        dotnet_package.mkdir()
        (dotnet_package / "ScriptHookRDRDotNet.asi").write_bytes(b"asi")
        (dotnet_package / "ScriptHookRDRNetAPI.dll").write_bytes(b"api")
        (dotnet_package / "ScriptHookRDRDotNet.ini").write_text("cfg", encoding="utf-8")
        manager.deploy_local(dotnet_package, self.game)
        self.assertEqual((self.game / "ScriptHookRDRDotNet.asi").read_bytes(), b"asi")
        self.assertEqual((self.game / "ScriptHookRDRNetAPI.dll").read_bytes(), b"api")
        self.assertEqual((self.game / "ScriptHookRDRDotNet.ini").read_text(encoding="utf-8"), "cfg")

        win32_only = self.root / "win32_only"
        (win32_only / "Win32").mkdir(parents=True)
        (win32_only / "Win32" / "dinput8.dll").write_bytes(b"bad")
        with self.assertRaises(InfrastructureError):
            manager.deploy_local(win32_only, self.game)

    def test_deploy_local_package_does_not_replace_an_existing_lml_folder(self) -> None:
        package = self.root / "package"
        (package / "bin").mkdir(parents=True)
        (package / "bin" / "ScriptHookRDR2.dll").write_bytes(b"hook")
        (package / "bin" / "dinput8.dll").write_bytes(b"loader")
        (package / "ModLoader").mkdir()
        (package / "ModLoader" / "vfs.asi").write_bytes(b"vfs")
        (package / "ModLoader" / "lml").mkdir()
        (package / "ModLoader" / "lml" / "example.txt").write_text("example", encoding="utf-8")
        manager = InfrastructureManager()
        result = manager.deploy_local(package, self.game)
        self.assertEqual((self.game / "ScriptHookRDR2.dll").read_bytes(), b"hook")
        self.assertEqual((self.game / "vfs.asi").read_bytes(), b"vfs")
        self.assertEqual((self.game / "lml" / "example.txt").read_text(encoding="utf-8"), "example")
        self.assertTrue(result.copied)

        user_file = self.game / "lml" / "user.txt"
        user_file.write_text("user", encoding="utf-8")
        (package / "ModLoader" / "lml" / "injected.txt").write_text("injected", encoding="utf-8")
        again = manager.deploy_local(package, self.game)
        self.assertTrue(user_file.is_file())
        self.assertFalse((self.game / "lml" / "injected.txt").exists())
        self.assertTrue(any("existing lml" in note for note in again.notes))

        archive = self.root / "hook.zip"
        make_zip(archive, {"bin/dinput8.dll": b"from-zip"})
        manager.deploy_local(archive, self.game)
        self.assertEqual((self.game / "dinput8.dll").read_bytes(), b"from-zip")

    def test_health_check_reports_quarantined_binaries(self) -> None:
        self.assertEqual(SCRIPT_HOOK_LABEL, "ScriptHookRDR2 V2")
        self.assertIn("mods/1472", SCRIPT_HOOK_PAGE)
        self.assertEqual(ASI_LOADER_LABEL, "Ultimate ASI Loader (x64)")
        self.assertTrue(ASI_LOADER_DOWNLOAD.endswith("dinput8-x64.zip"))
        self.assertEqual(LML_PACKAGE_NAME, "lml_rdr_beta_11.zip")
        self.assertEqual(DOTNET_VERSION, "1.0.5.5")
        self.assertTrue(DOTNET_DOWNLOAD.endswith("ScriptHookRDR2DotNet.rar"))
        self.assertEqual(
            [package.key for package in STANDARD_PACKAGES],
            ["scripthook_v2", "asi_loader_x64", "lml", "scripthook_dotnet"],
        )
        (self.game / "ScriptHookRDR2.dll").write_bytes(b"hook")
        (self.game / "dinput8.dll.off").write_bytes(b"loader")
        (self.game / "ScriptHookRDRDotNet.asi.off").write_bytes(b"dotnet")
        checked = InfrastructureManager().health_check(self.game)
        statuses = {item.filename: item.state for item in checked}
        labels = {item.filename: item.label for item in checked}
        self.assertEqual(statuses["ScriptHookRDR2.dll"], "present")
        self.assertEqual(statuses["dinput8.dll"], "quarantined")
        self.assertEqual(statuses["vfs.asi"], "missing")
        self.assertEqual(statuses["ScriptHookRDRDotNet.asi"], "quarantined")
        self.assertEqual(statuses["lml/"], "missing")
        self.assertEqual(labels["ScriptHookRDR2.dll"], "ScriptHookRDR2 V2")
        self.assertEqual(labels["dinput8.dll"], ASI_LOADER_LABEL)
        self.assertIn(DOTNET_VERSION, labels["ScriptHookRDRDotNet.asi"])

    def test_diagnostics_match_loader_failures_on_one_line(self) -> None:
        log_text = "ScriptHookRDR2 version mismatch\nVFS inject fail\n"
        findings = CrashDiagnostics().parse(log_text, self.game / "crash-main.log")
        self.assertEqual(
            {item.code for item in findings},
            {"scripthook_version", "vfs_injection"},
        )
        self.assertTrue(all(item.severity == "warning" for item in findings))

        home = self.root / "home"
        documents = home / "Documents" / "Rockstar Games" / "Red Dead Redemption 2"
        documents.mkdir(parents=True)
        (documents / "crash-main.log").write_text("old", encoding="utf-8")
        game_log = self.game / "crash-main.log"
        game_log.write_text(log_text, encoding="utf-8")
        with patch("core.diagnostics.Path.home", return_value=home):
            located = CrashDiagnostics().locate_log(self.game)
        self.assertEqual(located, game_log)

    def test_config_round_trip(self) -> None:
        path = self.root / "config.json"
        save_config(
            AppConfig(game_directory=str(self.game), active_profile="redm", redm_directory=None),
            path,
        )
        loaded = load_config(path)
        self.assertEqual(loaded.game_directory, str(self.game))
        self.assertEqual(loaded.active_profile, "redm")
        self.assertIsNone(loaded.redm_directory)

    def _tiny_archive(self, stem: str) -> Path:
        archive = self.root / f"{stem}.zip"
        make_zip(archive, {"Cool.asi": "asi", "stuff/model.ytd": "ytd"})
        return archive

    def _install(self, archive: Path) -> StagedInstall:
        staged = self.analyzer.stage(archive, self.game)
        written = self.analyzer.place(staged)
        self.store.save(
            ModManifest(
                mod_name=staged.metadata.name,
                archive_source=archive.name,
                files=[str(path) for path in written],
                author=staged.metadata.author,
                version=staged.metadata.version,
            )
        )
        self.analyzer.cleanup(staged)
        return staged


if __name__ == "__main__":
    unittest.main()
