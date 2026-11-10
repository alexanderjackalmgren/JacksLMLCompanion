"""Game-folder checks and local deployment of the standard RDR2 mod stack.

Standard packages:
- ScriptHookRDR2 V2 (kepmehz) for ``ScriptHookRDR2.dll``
- ThirteenAG Ultimate ASI Loader **x64** ``dinput8.dll``
- Lenny's Mod Loader RDR (``vfs.asi`` and friends)
- ScriptHookRDR2DotNet for .NET scripts (download URL may pin a release)

Optional addons:
- DLSSTweaks for RDR2 (``xinput9_1_0.dll`` + ``dlsstweaks.ini``)

GitHub packages (ASI Loader, DotNet) can be downloaded automatically. ScriptHook
V2 (Nexus), LML (expiring CDN links), and DLSSTweaks stay manual: open the page,
then pick the downloaded archive.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from core import CompanionError, GameDirectoryError, app_data_dir

GAME_EXECUTABLE = "RDR2.exe"

SCRIPT_HOOK_LABEL = "ScriptHookRDR2 V2"
SCRIPT_HOOK_PAGE = "https://www.nexusmods.com/reddeadredemption2/mods/1472"

ASI_LOADER_LABEL = "Ultimate ASI Loader (x64)"
ASI_LOADER_PAGE = "https://github.com/ThirteenAG/Ultimate-ASI-Loader"
ASI_LOADER_DOWNLOAD = (
    "https://github.com/ThirteenAG/Ultimate-ASI-Loader/releases/download/"
    "x64-latest/dinput8-x64.zip"
)

LML_LABEL = "Lenny's Mod Loader RDR"
LML_PAGE = "https://www.rdr2mods.com/downloads/rdr2/tools/76-lennys-mod-loader-rdr/"
LML_PACKAGE_NAME = "lml_rdr_beta_11.zip"

DOTNET_LABEL = "ScriptHookRDR2DotNet"
DOTNET_VERSION = "1.0.5.5"
DOTNET_PAGE = "https://github.com/slipzdev/ScriptHookRDR2DotNet/releases"
DOTNET_DOWNLOAD = (
    "https://github.com/slipzdev/ScriptHookRDR2DotNet/releases/download/"
    f"{DOTNET_VERSION}/ScriptHookRDR2DotNet.rar"
)

DLSS_TWEAKS_LABEL = "DLSSTweaks (optional)"
DLSS_TWEAKS_PAGE = "https://www.nexusmods.com/reddeadredemption2/mods/2072"
DLSS_TWEAKS_EXPECTED = "1. DLSSTweaks for RDR2 (.zip)"
DLSS_TWEAKS_CORE = ("xinput9_1_0.dll", "dlsstweaks.ini")
DLSS_TWEAKS_FILES = (
    "xinput9_1_0.dll",
    "dlsstweaks.ini",
    "DLSSTweaksConfig.exe",
)

DOWNLOAD_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class PackageSource:
    key: str
    label: str
    homepage: str
    provides: tuple[str, ...]
    download_url: str | None = None
    expected_archive: str | None = None


STANDARD_PACKAGES: tuple[PackageSource, ...] = (
    PackageSource(
        key="scripthook_v2",
        label=SCRIPT_HOOK_LABEL,
        homepage=SCRIPT_HOOK_PAGE,
        provides=("ScriptHookRDR2.dll",),
    ),
    PackageSource(
        key="asi_loader_x64",
        label=ASI_LOADER_LABEL,
        homepage=ASI_LOADER_PAGE,
        provides=("dinput8.dll",),
        download_url=ASI_LOADER_DOWNLOAD,
        expected_archive="dinput8-x64.zip",
    ),
    PackageSource(
        key="lml",
        label=LML_LABEL,
        homepage=LML_PAGE,
        provides=("vfs.asi",),
        expected_archive=LML_PACKAGE_NAME,
    ),
    PackageSource(
        key="scripthook_dotnet",
        label=DOTNET_LABEL,
        homepage=DOTNET_PAGE,
        provides=("ScriptHookRDRDotNet.asi",),
        download_url=DOTNET_DOWNLOAD,
        expected_archive="ScriptHookRDR2DotNet.rar",
    ),
)

DLSS_TWEAKS_PACKAGE = PackageSource(
    key="dlsstweaks",
    label=DLSS_TWEAKS_LABEL,
    homepage=DLSS_TWEAKS_PAGE,
    provides=DLSS_TWEAKS_CORE,
    expected_archive=DLSS_TWEAKS_EXPECTED,
)

OPTIONAL_ADDONS: tuple[PackageSource, ...] = (DLSS_TWEAKS_PACKAGE,)

REQUIRED_BINARIES = (
    ("ScriptHookRDR2.dll", SCRIPT_HOOK_LABEL, SCRIPT_HOOK_PAGE),
    ("dinput8.dll", ASI_LOADER_LABEL, ASI_LOADER_PAGE),
    ("vfs.asi", LML_LABEL, LML_PAGE),
    ("ScriptHookRDRDotNet.asi", DOTNET_LABEL, DOTNET_PAGE),
)

PAYLOAD_FILES = (
    "ScriptHookRDR2.dll",
    "dinput8.dll",
    "vfs.asi",
    "lml.ini",
    "ModManager.Core.dll",
    "ModManager.NativeInterop.dll",
    "NLog.dll",
    "ScriptHookRDRDotNet.asi",
    "ScriptHookRDRNetAPI.dll",
    "ScriptHookRDRDotNet.ini",
)

# Source aliases that still deploy as game-root dinput8.dll.
ASI_LOADER_ALIASES = (
    "dinput8.dll",
    "dinput8-x64.dll",
    "dinput8_x64.dll",
)

_X64_MARKERS = frozenset({"x64", "amd64", "win64"})
_WIN32_MARKERS = frozenset({"win32", "x86", "x32", "i386"})


class InfrastructureError(CompanionError):
    """A core binary could not be checked or deployed."""


@dataclass
class AppConfig:
    game_directory: str | None = None
    active_profile: str = "modded_story"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "game_directory": self.game_directory,
            "active_profile": self.active_profile,
        }


@dataclass(frozen=True)
class BinaryStatus:
    filename: str
    label: str
    state: str
    path: Path
    homepage: str


@dataclass
class DeployResult:
    copied: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PackageInstallOutcome:
    package: PackageSource
    status: str
    detail: str
    deploy: DeployResult | None = None


@dataclass
class InstallMissingResult:
    outcomes: list[PackageInstallOutcome] = field(default_factory=list)

    def short_summary(self) -> str:
        """Compact package list for dialogs."""
        if not self.outcomes:
            return "All standard infrastructure files are already present."
        lines: list[str] = []
        for item in self.outcomes:
            mark = {"deployed": "OK", "failed": "Failed", "skipped": "Skipped"}.get(
                item.status,
                item.status,
            )
            lines.append(f"{mark}: {item.package.label}")
        return "\n".join(lines)

    def detail_summary(self) -> str:
        """Expanded per-package detail for logs / Show Details."""
        if not self.outcomes:
            return "All standard infrastructure files are already present."
        blocks: list[str] = []
        for item in self.outcomes:
            blocks.append(f"{item.package.label}\n  {item.status}: {item.detail}")
        return "\n\n".join(blocks)

    def summary(self) -> str:
        return self.short_summary()

    @property
    def deployed(self) -> list[PackageInstallOutcome]:
        return [item for item in self.outcomes if item.status == "deployed"]

    @property
    def failed(self) -> list[PackageInstallOutcome]:
        return [item for item in self.outcomes if item.status == "failed"]

    @property
    def skipped(self) -> list[PackageInstallOutcome]:
        return [item for item in self.outcomes if item.status == "skipped"]


ProgressCallback = Callable[[str], None]
ManualPackageCallback = Callable[[PackageSource], Path | None]


class InfrastructureManager:
    """Validate the RDR2 folder and install the standard Script Hook / LML stack."""

    def validate_game_directory(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise GameDirectoryError(f"Folder does not exist: {resolved}")
        if not (resolved / GAME_EXECUTABLE).is_file():
            raise GameDirectoryError(
                f"RDR2.exe was not found in {resolved}. Choose the folder that contains RDR2.exe."
            )
        return resolved

    def health_check(self, game_dir: Path) -> list[BinaryStatus]:
        game_dir = self.validate_game_directory(game_dir)
        statuses: list[BinaryStatus] = []
        for filename, label, homepage in REQUIRED_BINARIES:
            active = game_dir / filename
            parked = game_dir / f"{filename}.off"
            if active.is_file():
                state = "present"
                located = active
            elif parked.is_file():
                state = "quarantined"
                located = parked
            else:
                state = "missing"
                located = active
            statuses.append(
                BinaryStatus(
                    filename=filename,
                    label=label,
                    state=state,
                    path=located,
                    homepage=homepage,
                )
            )
        lml_dir = game_dir / "lml"
        statuses.append(
            BinaryStatus(
                filename="lml/",
                label="LML mod folder",
                state="present" if lml_dir.is_dir() else "missing",
                path=lml_dir,
                homepage=LML_PAGE,
            )
        )
        statuses.extend(self.optional_addon_status(game_dir))
        return statuses

    def optional_addon_status(self, game_dir: Path) -> list[BinaryStatus]:
        """Status rows for optional addons (not part of required missing installs)."""
        game_dir = self.validate_game_directory(game_dir)
        statuses: list[BinaryStatus] = []
        for filename in DLSS_TWEAKS_CORE:
            active = game_dir / filename
            parked = game_dir / f"{filename}.off"
            if active.is_file():
                state = "present"
                located = active
            elif parked.is_file():
                state = "quarantined"
                located = parked
            else:
                state = "missing"
                located = active
            statuses.append(
                BinaryStatus(
                    filename=filename,
                    label=DLSS_TWEAKS_LABEL,
                    state=state,
                    path=located,
                    homepage=DLSS_TWEAKS_PAGE,
                )
            )
        return statuses

    def dlsstweaks_installed(self, game_dir: Path) -> bool:
        game_dir = self.validate_game_directory(game_dir)
        ini_ok = (game_dir / "dlsstweaks.ini").is_file()
        loader = game_dir / "xinput9_1_0.dll"
        parked = game_dir / "xinput9_1_0.dll.off"
        return ini_ok and (loader.is_file() or parked.is_file())

    def missing_packages(self, statuses: list[BinaryStatus] | None = None, game_dir: Path | None = None) -> list[PackageSource]:
        """Return standard packages needed for any missing required binary.

        Quarantined files count as present. The ``lml/`` folder alone does not
        select a package; Lenny's Mod Loader is requested when ``vfs.asi`` is missing.
        """
        if statuses is None:
            if game_dir is None:
                raise InfrastructureError("Provide a health-check result or a game folder.")
            statuses = self.health_check(game_dir)
        missing = {
            status.filename.casefold()
            for status in statuses
            if status.state == "missing" and not status.filename.endswith("/")
        }
        return [
            package
            for package in STANDARD_PACKAGES
            if any(name.casefold() in missing for name in package.provides)
        ]

    def download_package(self, package: PackageSource, dest_dir: Path | None = None) -> Path:
        """Download a package with a stable URL into the local cache."""
        if not package.download_url:
            raise InfrastructureError(
                f"{package.label} has no stable download URL. "
                "Open its page and deploy the archive manually."
            )
        cache = dest_dir or (app_data_dir() / "cache")
        cache.mkdir(parents=True, exist_ok=True)
        filename = package.expected_archive or Path(urlparse(package.download_url).path).name
        if not filename:
            raise InfrastructureError(f"Could not determine a filename for {package.label}.")
        target = cache / filename
        partial = cache / f"{filename}.partial"
        try:
            import requests
        except ImportError as exc:
            raise InfrastructureError("Downloading packages needs the requests package.") from exc
        try:
            with requests.get(
                package.download_url,
                stream=True,
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 64):
                        if chunk:
                            handle.write(chunk)
        except requests.RequestException as exc:
            partial.unlink(missing_ok=True)
            raise InfrastructureError(f"Could not download {package.label}: {exc}") from exc
        if not partial.is_file() or partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise InfrastructureError(f"Download for {package.label} was empty.")
        partial.replace(target)
        return target

    def install_missing(
        self,
        game_dir: Path,
        *,
        on_manual_needed: ManualPackageCallback,
        progress: ProgressCallback | None = None,
        packages: list[PackageSource] | None = None,
        cache_dir: Path | None = None,
    ) -> InstallMissingResult:
        """Install missing stack packages via auto-download or a manual file picker."""
        game_dir = self.validate_game_directory(game_dir)
        needed = packages if packages is not None else self.missing_packages(game_dir=game_dir)
        result = InstallMissingResult()
        if not needed:
            if progress:
                progress("All standard infrastructure files are already present.")
            return result

        def report(message: str) -> None:
            if progress:
                progress(message)

        for package in needed:
            try:
                if _package_needs_rar(package):
                    from core.rar_support import ensure_rar_backend

                    report(f"Preparing RAR support for {package.label}...")
                    ensure_rar_backend(progress=report)
                if package.download_url:
                    report(f"Downloading {package.label}...")
                    archive = self.download_package(package, cache_dir)
                    report(f"Deploying {package.label}...")
                    deploy = self.deploy_local(archive, game_dir)
                    result.outcomes.append(
                        PackageInstallOutcome(
                            package=package,
                            status="deployed",
                            detail=_deploy_detail(deploy, source=archive.name),
                            deploy=deploy,
                        )
                    )
                    continue
                report(f"Manual download required for {package.label}.")
                selected = on_manual_needed(package)
                if selected is None:
                    result.outcomes.append(
                        PackageInstallOutcome(
                            package=package,
                            status="skipped",
                            detail="User skipped the manual package.",
                        )
                    )
                    continue
                report(f"Deploying {package.label}...")
                deploy = self.deploy_local(selected, game_dir)
                result.outcomes.append(
                    PackageInstallOutcome(
                        package=package,
                        status="deployed",
                        detail=_deploy_detail(deploy, source=selected.name),
                        deploy=deploy,
                    )
                )
            except CompanionError as exc:
                result.outcomes.append(
                    PackageInstallOutcome(
                        package=package,
                        status="failed",
                        detail=str(exc),
                    )
                )
        return result

    def deploy_local(self, source: Path, game_dir: Path) -> DeployResult:
        """Copy known loader files from a folder, zip, or rar into the game folder.

        An existing ``lml`` directory is not replaced, so installed mods stay put.
        """
        game_dir = self.validate_game_directory(game_dir)
        source = source.expanduser().resolve()
        if not source.exists():
            raise InfrastructureError(f"Package not found: {source}")
        if source.is_dir():
            return self._deploy_tree(source, game_dir)
        if source.suffix.casefold() not in {".zip", ".rar"}:
            raise InfrastructureError("Deploy a folder, .zip, or .rar package.")
        from core.analyzer import extract_archive

        with tempfile.TemporaryDirectory(prefix="lml_payload_") as temporary:
            extract_root = Path(temporary)
            extract_archive(source, extract_root)
            return self._deploy_tree(extract_root, game_dir)

    def install_dlsstweaks(self, game_dir: Path, source: Path) -> DeployResult:
        """Deploy the Nexus ``1. DLSSTweaks for RDR2`` pack into the game folder.

        Expects ``xinput9_1_0.dll``, ``dlsstweaks.ini``, and optionally
        ``DLSSTweaksConfig.exe``. Configuration is left to the config tool / INI.
        """
        game_dir = self.validate_game_directory(game_dir)
        source = source.expanduser().resolve()
        if not source.exists():
            raise InfrastructureError(f"Package not found: {source}")
        if source.is_dir():
            return self._deploy_dlsstweaks_tree(source, game_dir)
        if source.suffix.casefold() in {".zip", ".rar"}:
            from core.analyzer import extract_archive

            with tempfile.TemporaryDirectory(prefix="dlsstweaks_") as temporary:
                extract_root = Path(temporary)
                extract_archive(source, extract_root)
                return self._deploy_dlsstweaks_tree(extract_root, game_dir)
        raise InfrastructureError("Deploy a folder, .zip, or .rar DLSSTweaks package.")

    def _deploy_dlsstweaks_tree(self, root: Path, game_dir: Path) -> DeployResult:
        found = _find_dlsstweaks_files(root)
        missing_core = [name for name in DLSS_TWEAKS_CORE if name.casefold() not in found]
        if missing_core:
            if "nvngx.dll" in found and "xinput9_1_0.dll" not in found:
                raise InfrastructureError(
                    "This looks like \"2. DLSSTweaks alternate loader\" (nvngx.dll). "
                    "Download \"1. DLSSTweaks for RDR2\" instead "
                    f"({', '.join(DLSS_TWEAKS_CORE)})."
                )
            raise InfrastructureError(
                "DLSSTweaks for RDR2 files were not found. Expected "
                f"{', '.join(DLSS_TWEAKS_CORE)}. On Nexus, download file "
                "\"1. DLSSTweaks for RDR2\"."
            )
        result = DeployResult()
        for key, source in found.items():
            if key == "nvngx.dll":
                continue
            destination = game_dir / source.name
            if source.resolve() == destination.resolve():
                result.notes.append(f"{destination.name} is already in the game folder.")
                continue
            shutil.copy2(source, destination)
            result.copied.append(destination)
        if not result.copied and not result.notes:
            result.notes.append("DLSSTweaks files were already in the game folder.")
        return result

    def _deploy_tree(self, root: Path, game_dir: Path) -> DeployResult:
        found, lml_dir = _find_payload(root)
        if not found and lml_dir is None:
            raise InfrastructureError(
                "No standard package files were found. Expected ScriptHookRDR2.dll, "
                "x64 dinput8.dll, vfs.asi, or ScriptHookRDRDotNet.asi in the folder, "
                "bin/, x64/, or ModLoader/."
            )
        result = DeployResult()
        for logical_name, source in found.items():
            destination_name = "dinput8.dll" if logical_name == "dinput8.dll" else source.name
            destination = game_dir / destination_name
            if source.resolve() == destination.resolve():
                result.notes.append(f"{destination_name} is already in the game folder.")
                continue
            shutil.copy2(source, destination)
            result.copied.append(destination)
            if logical_name == "dinput8.dll":
                result.notes.append(f"Deployed x64 ASI loader as {destination_name}.")
        game_lml = game_dir / "lml"
        if lml_dir is None:
            return result
        if game_lml.exists():
            result.notes.append("Left the existing lml folder in place.")
            return result
        shutil.copytree(lml_dir, game_lml)
        result.copied.append(game_lml)
        result.notes.append("Created the lml folder from the package.")
        return result


def _package_needs_rar(package: PackageSource) -> bool:
    archive = (package.expected_archive or "").casefold()
    url = (package.download_url or "").casefold()
    return archive.endswith(".rar") or url.endswith(".rar")


def _find_dlsstweaks_files(root: Path) -> dict[str, Path]:
    wanted = {name.casefold() for name in (*DLSS_TWEAKS_FILES, "nvngx.dll")}
    found: dict[str, Path] = {}
    for directory in _candidate_dirs(root):
        for path in directory.iterdir():
            if not path.is_file():
                continue
            key = path.name.casefold()
            if key not in wanted or key in found:
                continue
            found[key] = path
    return found


def _deploy_detail(deploy: DeployResult, *, source: str) -> str:
    names = [path.name for path in deploy.copied]
    if not names:
        files = "no new files"
    elif len(names) <= 2:
        files = ", ".join(names)
    else:
        files = f"{len(names)} files ({names[0]}, …)"
    detail = f"{files} from {source}"
    extras = [
        note
        for note in deploy.notes
        if "existing lml" in note.casefold() or "already in the game folder" in note.casefold()
    ]
    if extras:
        detail = f"{detail}. {extras[0]}"
    return detail


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or (app_data_dir() / "config.json")
    if not config_path.is_file():
        return AppConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanionError(f"Could not read {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompanionError(f"Config file is not a JSON object: {config_path}")
    game_directory = data.get("game_directory")
    active_profile = data.get("active_profile")
    if active_profile == "redm":
        active_profile = "vanilla_online"
    return AppConfig(
        game_directory=game_directory if isinstance(game_directory, str) and game_directory else None,
        active_profile=active_profile if isinstance(active_profile, str) and active_profile else "modded_story",
    )


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or (app_data_dir() / "config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
    return config_path


def _find_payload(root: Path) -> tuple[dict[str, Path], Path | None]:
    found: dict[str, Path] = {}
    lml_dir: Path | None = None
    loader_candidates: list[Path] = []

    for directory in _candidate_dirs(root):
        for name in PAYLOAD_FILES:
            if name.casefold() == "dinput8.dll":
                continue
            key = name.casefold()
            candidate = directory / name
            if not candidate.is_file():
                continue
            previous = found.get(key)
            if previous is None or _arch_rank(candidate) > _arch_rank(previous):
                found[key] = candidate
        for alias in ASI_LOADER_ALIASES:
            candidate = directory / alias
            if candidate.is_file():
                loader_candidates.append(candidate)
        child = directory / "lml"
        if lml_dir is None and child.is_dir():
            lml_dir = child

    chosen_loader = _choose_x64_loader(loader_candidates)
    if chosen_loader is not None:
        found["dinput8.dll"] = chosen_loader
    return found, lml_dir


def _choose_x64_loader(candidates: list[Path]) -> Path | None:
    """Pick the x64 dinput8.dll; refuse when only a Win32/x86 copy is present."""
    if not candidates:
        return None
    unique: dict[str, Path] = {}
    for path in candidates:
        unique[str(path.resolve())] = path
    usable = [path for path in unique.values() if not _is_win32_loader(path)]
    if not usable:
        raise InfrastructureError(
            "Found dinput8.dll, but only a Win32/x86 build. "
            "RDR2 needs the x64 ASI loader (for example dinput8.dll from an x64 folder "
            "or dinput8-x64.dll)."
        )
    return max(usable, key=_arch_rank)


def _is_win32_loader(path: Path) -> bool:
    return _has_win32_marker(path) and not _has_x64_marker(path)


def _has_x64_marker(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    stem = path.stem.casefold()
    name = path.name.casefold()
    return bool(parts & _X64_MARKERS) or any(
        marker in stem for marker in ("-x64", "_x64", ".x64")
    ) or name in {"dinput8-x64.dll", "dinput8_x64.dll"}


def _has_win32_marker(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    stem = path.stem.casefold()
    return bool(parts & _WIN32_MARKERS) or any(
        marker in stem for marker in ("-win32", "_win32", "-x86", "_x86", "-x32", "_x32")
    )


def _arch_rank(path: Path) -> int:
    """Higher ranks prefer explicit x64 paths and shorter package layouts."""
    score = 0
    if _has_x64_marker(path):
        score += 100
    if path.name.casefold() in {"dinput8-x64.dll", "dinput8_x64.dll"}:
        score += 20
    if _has_win32_marker(path):
        score -= 100
    score -= len(path.parts)
    return score


def _candidate_dirs(root: Path) -> list[Path]:
    """Walk likely package layouts, putting x64 folders ahead of Win32 ones."""
    if not root.is_dir():
        return [root]

    discovered: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_dir():
            return
        seen.add(resolved)
        discovered.append(path)

    add(root)
    preferred = ("x64", "amd64", "win64", "bin", "ModLoader", "Release")
    deferred = ("win32", "x86", "x32", "i386")
    for name in preferred:
        nested = root / name
        add(nested)
        if nested.is_dir():
            for child_name in preferred:
                add(nested / child_name)
    for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not child.is_dir():
            continue
        if child.name.casefold() in deferred:
            continue
        add(child)
        for name in preferred:
            add(child / name)
    for name in deferred:
        nested = root / name
        add(nested)
        if nested.is_dir():
            for child_name in ("bin", "Release"):
                add(nested / child_name)
    return discovered
