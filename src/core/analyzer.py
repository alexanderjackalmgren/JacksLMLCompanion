"""Archive extraction, install.xml parsing, and install routing.

Archives with ``install.xml`` use LML-aware routing. Archives without it are
treated as manual mods: the UI asks whether to install to the game root or an
LML folder. Generated ``install.xml`` is only written for the LML choice.
"""

from __future__ import annotations

import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core import CompanionError, GameDirectoryError, assert_within

FileKind = Literal["lml", "root"]
PlacementMode = Literal["root", "lml"]
ROOT_SCRIPT_SUFFIXES = {".asi", ".dll", ".ini"}
SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
README_NAMES = {
    "readme",
    "readme.txt",
    "readme.md",
    "read me.txt",
    "read_me.txt",
    "install.txt",
    "installation.txt",
}
MAX_ARCHIVE_FILES = 5000


class ArchiveError(CompanionError):
    """The archive could not be staged."""


@dataclass(frozen=True)
class ModMetadata:
    name: str
    author: str
    version: str
    generated: bool


@dataclass(frozen=True)
class PlannedFile:
    source: Path
    relative_destination: Path
    kind: FileKind


@dataclass
class StagedInstall:
    metadata: ModMetadata
    archive_source: Path
    staging_dir: Path
    game_dir: Path
    files: list[PlannedFile]
    warnings: list[str] = field(default_factory=list)
    needs_placement_choice: bool = False
    readme_path: Path | None = None
    has_install_xml: bool = False


@dataclass
class _XmlInfo:
    metadata: ModMetadata | None = None
    destinations: dict[str, Path] = field(default_factory=dict)
    warning: str | None = None


class ModAnalyzer:
    """Stages a mod archive and copies it into the game folder after clearance."""

    def __init__(self, staging_root: Path | None = None) -> None:
        from core import app_data_dir

        self.staging_root = staging_root or (app_data_dir() / "staging")

    def stage(self, archive: Path, game_dir: Path) -> StagedInstall:
        archive = archive.expanduser().resolve()
        game_dir = game_dir.expanduser().resolve()
        if not archive.is_file():
            raise ArchiveError(f"Archive not found: {archive}")
        if archive.suffix.casefold() not in {".zip", ".rar"}:
            raise ArchiveError("Choose a .zip or .rar mod archive.")
        if not (game_dir / "RDR2.exe").is_file():
            raise GameDirectoryError(
                "Choose the game folder that contains RDR2.exe before installing."
            )

        self.staging_root.mkdir(parents=True, exist_ok=True)
        slug = _safe_token(archive.stem)[:40] or "mod"
        staging_dir = self.staging_root / f"tmp_extract_{slug}_{uuid.uuid4().hex[:8]}"
        staging_dir.mkdir()
        try:
            extract_archive(archive, staging_dir)
            _unwrap_single_root(staging_dir)
            xml_info = _read_install_xml(staging_dir, _display_name(archive.stem))
            has_install_xml = xml_info.metadata is not None
            metadata = xml_info.metadata or ModMetadata(
                name=_display_name(archive.stem),
                author="Unknown",
                version="0.0.0",
                generated=True,
            )
            warnings = [xml_info.warning] if xml_info.warning else []
            readme_path = _find_readme(staging_dir)
            if has_install_xml:
                files = _route_tree(staging_dir, metadata, xml_info.destinations)
                _ensure_baseline_xml(staging_dir, metadata, files)
                if not files:
                    raise ArchiveError("Archive does not contain any installable files.")
                return StagedInstall(
                    metadata=metadata,
                    archive_source=archive,
                    staging_dir=staging_dir,
                    game_dir=game_dir,
                    files=files,
                    warnings=warnings,
                    needs_placement_choice=False,
                    readme_path=readme_path,
                    has_install_xml=True,
                )
            pending = _collect_source_files(staging_dir)
            if not pending:
                raise ArchiveError("Archive does not contain any installable files.")
            warnings.append(
                "No install.xml found. Choose game root or LML before files are copied."
            )
            return StagedInstall(
                metadata=metadata,
                archive_source=archive,
                staging_dir=staging_dir,
                game_dir=game_dir,
                files=[],
                warnings=warnings,
                needs_placement_choice=True,
                readme_path=readme_path,
                has_install_xml=False,
            )
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

    def apply_placement(self, staged: StagedInstall, mode: PlacementMode) -> None:
        """Resolve destinations for a manual mod after the user chooses root or LML."""
        if not staged.needs_placement_choice:
            raise ArchiveError("This mod already has an install plan.")
        sources = _collect_source_files(staged.staging_dir)
        if not sources:
            raise ArchiveError("Archive does not contain any installable files.")
        if mode == "root":
            planned: list[PlannedFile] = []
            for source in sources:
                relative = source.relative_to(staged.staging_dir)
                if relative.name.casefold() == "rdr2.exe":
                    raise ArchiveError("Refusing to stage a replacement RDR2.exe.")
                planned.append(PlannedFile(source, relative, "root"))
            staged.files = planned
        else:
            staged.files = _route_tree(staged.staging_dir, staged.metadata, {})
            _ensure_baseline_xml(staged.staging_dir, staged.metadata, staged.files)
        if not staged.files:
            raise ArchiveError("Archive does not contain any installable files.")
        staged.needs_placement_choice = False

    def place(self, staged: StagedInstall) -> list[Path]:
        """Copy staged files into the game folder. Rolls back copies on failure."""
        if staged.needs_placement_choice or not staged.files:
            raise ArchiveError("Choose where to install this mod before copying files.")
        written: list[Path] = []
        try:
            for planned in staged.files:
                destination = assert_within(
                    staged.game_dir,
                    staged.game_dir / planned.relative_destination,
                )
                if planned.kind == "root" and destination.name.casefold() == "rdr2.exe":
                    raise ArchiveError("Refusing to replace RDR2.exe.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(planned.source, destination)
                written.append(destination)
        except Exception as exc:
            for path in reversed(written):
                path.unlink(missing_ok=True)
            if isinstance(exc, CompanionError):
                raise
            raise ArchiveError(f"Could not copy mod files: {exc}") from exc
        return written

    def cleanup(self, staged: StagedInstall) -> None:
        staging = staged.staging_dir.resolve()
        root = self.staging_root.resolve()
        if staging.parent != root or not staging.name.startswith("tmp_extract_"):
            raise ArchiveError(f"Refusing to delete unexpected staging directory: {staging}")
        shutil.rmtree(staging, ignore_errors=True)


def extract_archive(archive: Path, destination: Path) -> None:
    """Extract a zip or rar archive, rejecting paths that escape ``destination``."""
    suffix = archive.suffix.casefold()
    if suffix == ".zip":
        _extract_zip(archive, destination)
        return
    if suffix == ".rar":
        _extract_rar(archive, destination)
        return
    raise ArchiveError(f"Unsupported archive type: {archive.suffix}")


def _extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ArchiveError("Archive contains too many files.")
            for member in members:
                _reject_unsafe_member(destination, member.filename, _zip_is_symlink(member))
            bundle.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise ArchiveError("That zip archive is damaged or incomplete.") from exc


def _extract_rar(archive: Path, destination: Path) -> None:
    try:
        import rarfile
    except ImportError as exc:
        raise ArchiveError("RAR archives need the rarfile package.") from exc
    from core.rar_support import RarSupportError, ensure_rar_backend

    try:
        ensure_rar_backend()
    except RarSupportError as exc:
        raise ArchiveError(str(exc)) from exc
    destination = destination.resolve()
    try:
        with rarfile.RarFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ArchiveError("Archive contains too many files.")
            for member in members:
                _reject_unsafe_member(destination, member.filename, False)
            bundle.extractall(destination)
    except ArchiveError:
        raise
    except rarfile.RarCannotExec as exc:
        raise ArchiveError(
            "Could not run a RAR extractor. Install 7-Zip or UnRAR and retry."
        ) from exc
    except Exception as exc:
        raise ArchiveError(
            "Could not read that RAR archive. Confirm the file is not damaged."
        ) from exc


def _zip_is_symlink(member: zipfile.ZipInfo) -> bool:
    mode = (member.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _reject_unsafe_member(destination: Path, name: str, is_symlink: bool) -> None:
    if is_symlink:
        raise ArchiveError(f"Refusing to extract a symlink: {name}")
    relative = Path(name)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ArchiveError(f"Unsafe path in archive: {name}")
    target = destination.joinpath(relative).resolve()
    try:
        target.relative_to(destination)
    except ValueError as exc:
        raise ArchiveError(f"Unsafe path in archive: {name}") from exc


def _unwrap_single_root(staging: Path) -> None:
    entries = [
        path
        for path in staging.iterdir()
        if path.name != "__MACOSX" and not path.name.startswith(".")
    ]
    if len(entries) != 1 or not entries[0].is_dir():
        return
    wrapper = entries[0]
    for child in wrapper.iterdir():
        shutil.move(str(child), str(staging / child.name))
    wrapper.rmdir()


def _read_install_xml(staging: Path, fallback_name: str) -> _XmlInfo:
    candidates = [
        path
        for path in staging.rglob("install.xml")
        if path.is_file() and "__MACOSX" not in path.parts
    ]
    if not candidates:
        return _XmlInfo()
    install_xml = min(candidates, key=lambda path: len(path.relative_to(staging).parts))
    try:
        root = ET.parse(install_xml).getroot()
    except ET.ParseError:
        return _XmlInfo(warning=f"Ignored unreadable install.xml: {install_xml.name}")

    name = _xml_text(root, "name") or fallback_name
    author = _xml_text(root, "author") or "Unknown"
    version = _xml_text(root, "version") or "0.0.0"
    metadata = ModMetadata(
        name=_safe_folder_name(name),
        author=author,
        version=version,
        generated=not bool(_xml_text(root, "name")),
    )
    destinations: dict[str, Path] = {}
    # Legacy/simple manifests.
    for node in _xml_elements(root, "file"):
        source = (_xml_child_text(node, "source") or "").strip().replace("\\", "/")
        declared = (_xml_child_text(node, "destination") or "").strip().replace("\\", "/")
        if not source or not declared:
            continue
        try:
            destinations[_rel_key(Path(source))] = _safe_relative(declared)
        except ArchiveError as exc:
            return _XmlInfo(metadata=metadata, warning=str(exc))
    # Lenny EasyInstall FileReplacement entries (FilePath is the mod-local file).
    for node in _xml_elements(root, "FileReplacement"):
        source = (_xml_child_text(node, "FilePath") or "").strip().replace("\\", "/")
        if not source:
            continue
        try:
            destinations[_rel_key(Path(source))] = _safe_relative(source)
        except ArchiveError as exc:
            return _XmlInfo(metadata=metadata, warning=str(exc))
    return _XmlInfo(metadata=metadata, destinations=destinations)


def _collect_source_files(staging: Path) -> list[Path]:
    files: list[Path] = []
    for path in staging.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(staging)
        if _ignored(relative):
            continue
        files.append(path)
    return files


def _find_readme(staging: Path) -> Path | None:
    candidates: list[Path] = []
    for path in _collect_source_files(staging):
        name = path.name.casefold()
        if name in README_NAMES or name.startswith("readme"):
            candidates.append(path)
    if not candidates:
        return None
    return min(candidates, key=lambda path: (len(path.relative_to(staging).parts), path.name.casefold()))


def _route_tree(
    staging: Path,
    metadata: ModMetadata,
    destinations: dict[str, Path],
) -> list[PlannedFile]:
    mod_folder = _safe_folder_name(metadata.name)
    planned: list[PlannedFile] = []
    for path in _collect_source_files(staging):
        relative = path.relative_to(staging)
        declared = destinations.get(_rel_key(relative))
        kind, destination = _route_destination(relative, declared, mod_folder)
        if kind == "root" and path.name.casefold() == "rdr2.exe":
            raise ArchiveError("Refusing to stage a replacement RDR2.exe.")
        planned.append(PlannedFile(path, destination, kind))
    return planned


def _route_destination(
    relative: Path,
    declared: Path | None,
    mod_folder: str,
) -> tuple[FileKind, Path]:
    suffix = relative.suffix.casefold()
    if declared is not None:
        if declared.parts and declared.parts[0].casefold() == "lml":
            return "lml", declared
        if len(declared.parts) == 1 and suffix in ROOT_SCRIPT_SUFFIXES:
            return "root", declared
        return "lml", Path("lml") / mod_folder / declared
    if len(relative.parts) == 1 and suffix in ROOT_SCRIPT_SUFFIXES:
        return "root", Path(relative.name)
    if relative.parts and relative.parts[0].casefold() == "lml":
        return "lml", relative
    return "lml", Path("lml") / mod_folder / relative


def _ensure_baseline_xml(
    staging: Path,
    metadata: ModMetadata,
    files: list[PlannedFile],
) -> None:
    if any(item.relative_destination.name.casefold() == "install.xml" for item in files):
        return
    mod_folder = _safe_folder_name(metadata.name)
    baseline = staging / "_generated_install.xml"
    root = ET.Element("easy")
    ET.SubElement(root, "name").text = metadata.name
    ET.SubElement(root, "author").text = metadata.author
    ET.SubElement(root, "version").text = metadata.version
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(baseline, encoding="utf-8", xml_declaration=True)
    files.append(
        PlannedFile(
            source=baseline,
            relative_destination=Path("lml") / mod_folder / "install.xml",
            kind="lml",
        )
    )


def _ignored(relative: Path) -> bool:
    if any(part == "__MACOSX" or part.startswith(".") for part in relative.parts):
        return True
    return relative.name.casefold() in SKIP_NAMES


def _safe_relative(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ArchiveError(f"Unsafe destination in install.xml: {value}")
    return relative


def _xml_local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _xml_elements(root: ET.Element, tag: str) -> list[ET.Element]:
    wanted = tag.casefold()
    return [
        node
        for node in root.iter()
        if _xml_local_name(node.tag).casefold() == wanted
    ]


def _xml_child_text(node: ET.Element, tag: str) -> str:
    wanted = tag.casefold()
    for child in list(node):
        if _xml_local_name(child.tag).casefold() == wanted and child.text and child.text.strip():
            return child.text.strip()
    return ""


def _xml_text(root: ET.Element, tag: str) -> str:
    """Read the first matching element text, case-insensitive (EasyInstall uses PascalCase)."""
    for node in _xml_elements(root, tag):
        if node.text and node.text.strip():
            return node.text.strip()
    return ""


def _rel_key(relative: Path) -> str:
    return relative.as_posix().casefold()


def _display_name(stem: str) -> str:
    return _safe_folder_name(stem.replace(".", " "))


def _safe_folder_name(name: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name).strip().rstrip(".")
    return cleaned[:80] or "Unnamed Mod"


def _safe_token(value: str) -> str:
    token = "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._")
    return token or "mod"
