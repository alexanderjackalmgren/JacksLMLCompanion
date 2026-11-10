"""JSON manifests and the uninstall path that consumes them.

Each installed mod gets one file in ``mod_manifests/``. The file lists the
absolute paths that were written so removal does not guess which files belong
to the mod.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core import CompanionError, app_data_dir, assert_within

_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


class ManifestError(CompanionError):
    """A manifest could not be read, written, or applied."""


@dataclass
class ModManifest:
    mod_name: str
    archive_source: str
    files: list[str]
    author: str = "Unknown"
    version: str = "0.0.0"

    def to_dict(self) -> dict[str, object]:
        return {
            "mod_name": self.mod_name,
            "archive_source": self.archive_source,
            "author": self.author,
            "version": self.version,
            "files": list(self.files),
        }

    @classmethod
    def from_dict(cls, data: object, source: Path) -> ModManifest:
        if not isinstance(data, dict):
            raise ManifestError(f"Manifest is not a JSON object: {source}")
        name = data.get("mod_name")
        archive_source = data.get("archive_source")
        files = data.get("files")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError(f"Manifest is missing mod_name: {source}")
        if not isinstance(archive_source, str):
            raise ManifestError(f"Manifest is missing archive_source: {source}")
        if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
            raise ManifestError(f"Manifest file list is invalid: {source}")
        author = data.get("author")
        version = data.get("version")
        return cls(
            mod_name=name.strip(),
            archive_source=archive_source,
            files=list(files),
            author=author.strip() if isinstance(author, str) and author.strip() else "Unknown",
            version=version.strip() if isinstance(version, str) and version.strip() else "0.0.0",
        )


@dataclass
class UninstallResult:
    mod_name: str
    removed_files: list[Path] = field(default_factory=list)
    missing_files: list[Path] = field(default_factory=list)
    removed_directories: list[Path] = field(default_factory=list)


class ManifestStore:
    """Reads and writes ``mod_manifests/*.json``."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or (app_data_dir() / "mod_manifests")
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, manifest: ModManifest) -> Path:
        path = self._path_for(manifest.mod_name) or self._new_path(manifest.mod_name)
        try:
            path.write_text(
                json.dumps(manifest.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ManifestError(f"Could not write manifest {path.name}: {exc}") from exc
        return path

    def load(self, mod_name: str) -> ModManifest:
        path = self._path_for(mod_name)
        if path is None:
            raise ManifestError(f"No manifest found for {mod_name}.")
        return self._load_path(path)

    def list_manifests(self) -> list[ModManifest]:
        manifests = [self._load_path(path) for path in sorted(self.directory.glob("*.json"))]
        manifests.sort(key=lambda item: item.mod_name.casefold())
        return manifests

    def uninstall(self, mod_name: str, game_dir: Path) -> UninstallResult:
        """Delete tracked files, prune empty folders, then delete the manifest.

        Nothing is deleted when a tracked path is outside the game folder, is
        not a file, or is the root ``RDR2.exe``. A failed delete keeps the
        manifest so the remaining files can be removed on a later attempt.
        """
        path = self._path_for(mod_name)
        if path is None:
            raise ManifestError(f"No manifest found for {mod_name}.")
        manifest = self._load_path(path)
        game_dir = game_dir.expanduser().resolve()
        removable: list[Path] = []
        missing: list[Path] = []
        refused: list[Path] = []
        for raw in manifest.files:
            candidate = Path(raw)
            if not candidate.exists():
                missing.append(candidate)
                continue
            if not candidate.is_file():
                refused.append(candidate)
                continue
            resolved = candidate.resolve()
            if resolved.name.casefold() == "rdr2.exe" and resolved.parent == game_dir:
                refused.append(resolved)
                continue
            try:
                removable.append(assert_within(game_dir, resolved))
            except CompanionError:
                refused.append(resolved)

        if refused:
            listed = "\n".join(str(item) for item in refused)
            raise ManifestError(
                "Uninstall stopped so the manifest could be kept. "
                "These paths are protected or outside the game folder:\n"
                f"{listed}"
            )

        result = UninstallResult(mod_name=manifest.mod_name, missing_files=missing)
        try:
            for file_path in removable:
                file_path.unlink()
                result.removed_files.append(file_path)
                result.removed_directories.extend(_prune_empty_dirs(file_path.parent, game_dir))
        except OSError as exc:
            raise ManifestError(
                f"Stopped while deleting files for {mod_name}. The manifest was kept. {exc}"
            ) from exc
        path.unlink()
        return result

    def _load_path(self, path: Path) -> ModManifest:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Could not read manifest {path.name}: {exc}") from exc
        return ModManifest.from_dict(data, path)

    def _path_for(self, mod_name: str) -> Path | None:
        for path in self.directory.glob("*.json"):
            if self._load_path(path).mod_name == mod_name:
                return path
        return None

    def _new_path(self, mod_name: str) -> Path:
        slug = _SLUG.sub("_", mod_name).strip("._") or "mod"
        candidate = self.directory / f"{slug}.json"
        if not candidate.exists():
            return candidate
        digest = hashlib.sha256(mod_name.encode("utf-8")).hexdigest()[:8]
        return self.directory / f"{slug}_{digest}.json"


def _prune_empty_dirs(start: Path, game_dir: Path) -> list[Path]:
    removed: list[Path] = []
    game_dir = game_dir.resolve()
    lml_root = (game_dir / "lml").resolve()
    current = start.resolve()
    while current not in {game_dir, lml_root}:
        try:
            current.relative_to(game_dir)
        except ValueError:
            break
        if any(current.iterdir()):
            break
        current.rmdir()
        removed.append(current)
        current = current.parent
    return removed
