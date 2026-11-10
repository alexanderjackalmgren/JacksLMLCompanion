"""Detect root-file and LML-folder collisions before anything is copied."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core import path_key
from core.analyzer import StagedInstall
from core.manifest import ManifestStore


REINSTALL = "reinstall"
ROOT_OVERWRITE = "root_overwrite"
LML_FOLDER = "lml_folder"


@dataclass(frozen=True)
class Collision:
    kind: str
    incoming: str
    existing_mod: str | None
    message: str


class CollisionDetector:
    """Compare a staged install with manifests and the game folder."""

    def detect(self, staged: StagedInstall, store: ManifestStore) -> list[Collision]:
        manifests = store.list_manifests()
        same = next((item for item in manifests if item.mod_name == staged.metadata.name), None)
        others = [item for item in manifests if item is not same]
        owned_files = _owned_files(others, staged.game_dir)
        owned_folders = _owned_folders(others, staged.game_dir)
        same_files = _file_keys(same.files, staged.game_dir) if same else set()
        same_folders = _folder_names(same.files, staged.game_dir) if same else set()
        disk_folders = _disk_lml_folders(staged.game_dir)

        collisions: list[Collision] = []
        if same is not None:
            collisions.append(
                Collision(
                    kind=REINSTALL,
                    incoming=same.mod_name,
                    existing_mod=same.mod_name,
                    message=f"{same.mod_name} is already installed.",
                )
            )

        reported_folders: set[str] = set()
        for planned in staged.files:
            destination = staged.game_dir / planned.relative_destination
            if planned.kind == "root":
                collisions.extend(_root_collision(destination, owned_files, same_files))
                continue
            folder = _relative_lml_folder(planned.relative_destination)
            if folder is None:
                continue
            key = folder.casefold()
            if key in reported_folders:
                continue
            reported_folders.add(key)
            collision = _folder_collision(folder, owned_folders, disk_folders, same_folders)
            if collision is not None:
                collisions.append(collision)
        return collisions


def _root_collision(
    destination: Path,
    owned_files: dict[str, str],
    same_files: set[str],
) -> list[Collision]:
    key = path_key(destination)
    owner = owned_files.get(key)
    if owner:
        return [
            Collision(
                kind=ROOT_OVERWRITE,
                incoming=destination.name,
                existing_mod=owner,
                message=f"{destination.name} is owned by {owner}.",
            )
        ]
    if key in same_files or not destination.exists():
        return []
    return [
        Collision(
            kind=ROOT_OVERWRITE,
            incoming=destination.name,
            existing_mod=None,
            message=(
                f"{destination.name} already exists in the game folder "
                "and is not tracked by a manifest."
            ),
        )
    ]


def _folder_collision(
    folder: str,
    owned_folders: dict[str, str],
    disk_folders: dict[str, str],
    same_folders: set[str],
) -> Collision | None:
    key = folder.casefold()
    owner = owned_folders.get(key)
    if owner:
        return Collision(
            kind=LML_FOLDER,
            incoming=folder,
            existing_mod=owner,
            message=f"LML folder '{folder}' is used by {owner}.",
        )
    if key in disk_folders and key not in same_folders:
        return Collision(
            kind=LML_FOLDER,
            incoming=folder,
            existing_mod=None,
            message=f"LML folder '{disk_folders[key]}' already exists.",
        )
    return None


def _owned_files(manifests: list, game_dir: Path) -> dict[str, str]:
    owned: dict[str, str] = {}
    for manifest in manifests:
        for raw in manifest.files:
            path = Path(raw)
            try:
                path.resolve().relative_to(game_dir.resolve())
            except ValueError:
                continue
            owned[path_key(path)] = manifest.mod_name
    return owned


def _file_keys(files: list[str], game_dir: Path) -> set[str]:
    keys: set[str] = set()
    for raw in files:
        path = Path(raw)
        try:
            path.resolve().relative_to(game_dir.resolve())
        except ValueError:
            continue
        keys.add(path_key(path))
    return keys


def _owned_folders(manifests: list, game_dir: Path) -> dict[str, str]:
    owned: dict[str, str] = {}
    for manifest in manifests:
        for folder in _folder_names(manifest.files, game_dir):
            owned.setdefault(folder, manifest.mod_name)
    return owned


def _folder_names(files: list[str], game_dir: Path) -> set[str]:
    names: set[str] = set()
    game_dir = game_dir.resolve()
    for raw in files:
        try:
            relative = Path(raw).resolve().relative_to(game_dir)
        except ValueError:
            continue
        folder = _relative_lml_folder(relative)
        if folder:
            names.add(folder.casefold())
    return names


def _relative_lml_folder(relative: Path) -> str | None:
    if len(relative.parts) >= 2 and relative.parts[0].casefold() == "lml":
        return relative.parts[1]
    return None


def _disk_lml_folders(game_dir: Path) -> dict[str, str]:
    lml_root = game_dir / "lml"
    if not lml_root.is_dir():
        return {}
    return {path.name.casefold(): path.name for path in lml_root.iterdir() if path.is_dir()}
