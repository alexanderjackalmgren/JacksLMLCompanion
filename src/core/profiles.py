"""Switch between Modded Story, Vanilla Online, and RedM.

Online and RedM quarantine the ASI loader and root ``.asi`` plugins by
renaming them with a ``.off`` suffix. Files under ``lml/`` are left in place.
Modded Story restores those quarantined names. Both the active file and the
``.off`` file are never deleted; if both exist, the switch stops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from core import CompanionError, GameDirectoryError, app_data_dir


class Profile(Enum):
    MODDED_STORY = "modded_story"
    VANILLA_ONLINE = "vanilla_online"
    REDM = "redm"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Profile.MODDED_STORY: "Modded Story",
    Profile.VANILLA_ONLINE: "Vanilla Online",
    Profile.REDM: "RedM",
}


class ProfileError(CompanionError):
    """A profile switch could not be completed safely."""


@dataclass(frozen=True)
class FileAction:
    source: str
    destination: str
    action: str
    detail: str


@dataclass
class SwitchReport:
    profile: Profile
    actions: list[FileAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Profile: {self.profile.label}", *self.notes]
        lines.extend(item.detail for item in self.actions)
        return "\n".join(lines)


class ProfileSwitcher:
    """Rename loader files in the game root to match the selected profile."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or (app_data_dir() / "profile_state.json")

    def current(self) -> Profile:
        if not self.state_path.is_file():
            return Profile.MODDED_STORY
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return Profile(data["active_profile"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return Profile.MODDED_STORY

    def switch(self, game_dir: Path, profile: Profile) -> SwitchReport:
        game_dir = game_dir.expanduser().resolve()
        if not (game_dir / "RDR2.exe").is_file():
            raise GameDirectoryError(
                "Refusing to change loaders in a folder that does not contain RDR2.exe."
            )
        actions = _plan(game_dir, profile)
        conflicts = [item for item in actions if item.action == "conflict"]
        if conflicts:
            detail = "\n".join(item.detail for item in conflicts)
            raise ProfileError(
                "Switch stopped because both the active file and its .off copy exist:\n" + detail
            )
        completed: list[FileAction] = []
        try:
            for item in actions:
                if item.action != "rename":
                    continue
                Path(item.source).replace(Path(item.destination))
                completed.append(item)
        except OSError as exc:
            for item in reversed(completed):
                Path(item.destination).replace(Path(item.source))
            raise ProfileError(f"Could not rename loader files. Changes were rolled back. {exc}") from exc
        report = SwitchReport(profile=profile, actions=actions, notes=_notes(profile))
        self._write_state(profile)
        return report

    def _write_state(self, profile: Profile) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active_profile": profile.value}
        self.state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _plan(game_dir: Path, profile: Profile) -> list[FileAction]:
    enable = profile is Profile.MODDED_STORY
    actions: list[FileAction] = []
    if enable:
        for parked in _parked_files(game_dir):
            active = parked.with_name(parked.name[:-4])
            actions.append(_pair(active, parked, enable=True))
    else:
        for active in _active_files(game_dir):
            actions.append(_pair(active, Path(str(active) + ".off"), enable=False))
        for parked in _parked_files(game_dir):
            active = parked.with_name(parked.name[:-4])
            if active.is_file():
                continue
            actions.append(
                FileAction(
                    source=str(parked),
                    destination=str(parked),
                    action="unchanged",
                    detail=f"{active.name} is already quarantined.",
                )
            )
    loader = game_dir / "dinput8.dll"
    parked_loader = game_dir / "dinput8.dll.off"
    if not loader.exists() and not parked_loader.exists():
        actions.append(
            FileAction(
                source=str(loader),
                destination=str(parked_loader),
                action="missing",
                detail="dinput8.dll is not in the game folder.",
            )
        )
    return actions


def _pair(active: Path, parked: Path, enable: bool) -> FileAction:
    if active.is_file() and parked.is_file():
        return FileAction(
            source=str(active),
            destination=str(parked),
            action="conflict",
            detail=f"Both {active.name} and {parked.name} exist.",
        )
    if enable:
        if parked.is_file():
            return FileAction(
                source=str(parked),
                destination=str(active),
                action="rename",
                detail=f"Restored {active.name}.",
            )
        return FileAction(
            source=str(active),
            destination=str(active),
            action="unchanged",
            detail=f"{active.name} is already active.",
        )
    if active.is_file():
        return FileAction(
            source=str(active),
            destination=str(parked),
            action="rename",
            detail=f"Quarantined {active.name}.",
        )
    return FileAction(
        source=str(parked),
        destination=str(parked),
        action="unchanged",
        detail=f"{active.name} is already quarantined.",
    )


def _active_files(game_dir: Path) -> list[Path]:
    return _files_named(game_dir, loader="dinput8.dll", suffix=".asi")


def _parked_files(game_dir: Path) -> list[Path]:
    return _files_named(game_dir, loader="dinput8.dll.off", suffix=".asi.off")


def _files_named(game_dir: Path, loader: str, suffix: str) -> list[Path]:
    found: list[Path] = []
    for path in game_dir.iterdir():
        if not path.is_file():
            continue
        name = path.name.casefold()
        if name == loader or name.endswith(suffix):
            found.append(path)
    return sorted(found, key=lambda item: item.name.casefold())


def _notes(profile: Profile) -> list[str]:
    if profile is Profile.MODDED_STORY:
        return ["ScriptHookRDR2 V2's ASI loader and root .asi plugins are restored."]
    if profile is Profile.VANILLA_ONLINE:
        return [
            "ASI loaders and root .asi plugins are renamed with a .off suffix so online mode will not load them.",
            "Files under lml/ were left in place.",
        ]
    return [
        "Single-player script loaders are quarantined.",
        "Point the RedM client at this game folder. Automatic client linking is not set up yet.",
        "Files under lml/ were left in place.",
    ]
