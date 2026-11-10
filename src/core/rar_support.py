"""Locate or bootstrap a RAR extraction backend for ``rarfile``.

Prefers an existing UnRAR/7-Zip install. On Windows, if nothing usable is found,
downloads RARLAB's free command-line UnRAR into the app ``tools/`` folder.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from core import CompanionError, app_data_dir

UNRAR_DOWNLOAD_URL = "https://www.rarlab.com/rar/unrarw64.exe"
ProgressCallback = Callable[[str], None]


class RarSupportError(CompanionError):
    """A RAR backend could not be found or installed."""


def ensure_rar_backend(progress: ProgressCallback | None = None) -> Path | str:
    """Make ``rarfile`` able to extract archives. Returns the tool path or label."""
    import rarfile

    existing = _working_tool(rarfile)
    if existing is not None:
        return existing

    for candidate in _candidate_tools():
        if _try_configure(rarfile, candidate):
            if progress:
                progress(f"Using RAR tool: {candidate}")
            return candidate

    if sys.platform != "win32":
        raise RarSupportError(
            "No RAR extractor found. Install UnRAR (or 7-Zip with RAR support) and retry."
        )

    tool = _bootstrap_windows_unrar(progress)
    if _try_configure(rarfile, tool):
        if progress:
            progress(f"Installed RAR tool: {tool}")
        return tool
    raise RarSupportError(
        "Downloaded UnRAR, but it could not be started. "
        "Install UnRAR or 7-Zip manually and retry."
    )


def _working_tool(rarfile_module) -> Path | str | None:
    try:
        setup = rarfile_module.tool_setup(force=True)
    except rarfile_module.RarCannotExec:
        return None
    cmdline = setup.get_cmdline("check_cmd", None)
    tool = Path(cmdline[0]) if cmdline else None
    if tool and tool.is_file():
        return tool
    return cmdline[0] if cmdline else "configured"


def _try_configure(rarfile_module, tool: Path) -> bool:
    name = tool.name.casefold()
    if name in {"7z.exe", "7z", "7zz", "7zz.exe"}:
        rarfile_module.SEVENZIP_TOOL = str(tool)
        rarfile_module.SEVENZIP2_TOOL = str(tool)
    else:
        rarfile_module.UNRAR_TOOL = str(tool)
    try:
        rarfile_module.tool_setup(force=True)
    except rarfile_module.RarCannotExec:
        return False
    return True


def _candidate_tools() -> list[Path]:
    names = ("UnRAR.exe", "unrar.exe", "unrar", "7z.exe", "7z", "7zz.exe", "7zz")
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = str(path.resolve())
        except OSError:
            return
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        found.append(path)

    tools_dir = app_data_dir() / "tools"
    for name in names:
        add(tools_dir / name)

    for name in names:
        which = shutil.which(name)
        if which:
            add(Path(which))

    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        for root in (pf, pf86, local):
            if not root:
                continue
            base = Path(root)
            add(base / "7-Zip" / "7z.exe")
            add(base / "WinRAR" / "UnRAR.exe")
            add(base / "WinRAR" / "unrar.exe")
    return found


def _bootstrap_windows_unrar(progress: ProgressCallback | None) -> Path:
    import subprocess

    tools = app_data_dir() / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    target = tools / "UnRAR.exe"
    if target.is_file() and target.stat().st_size > 0:
        return target
    if progress:
        progress("Downloading free UnRAR command-line tool from rarlab.com...")
    try:
        import requests
    except ImportError as exc:
        raise RarSupportError("Downloading UnRAR needs the requests package.") from exc
    sfx = tools / "unrarw64.exe"
    partial = tools / "unrarw64.exe.partial"
    try:
        with requests.get(
            UNRAR_DOWNLOAD_URL,
            stream=True,
            timeout=120,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        handle.write(chunk)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise RarSupportError(f"Could not download UnRAR: {exc}") from exc
    if not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        raise RarSupportError("Downloaded UnRAR package was empty.")
    partial.replace(sfx)
    if progress:
        progress("Installing UnRAR into the app tools folder...")
    try:
        completed = subprocess.run(
            [str(sfx), "/s"],
            cwd=str(tools),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RarSupportError(f"Could not install UnRAR: {exc}") from exc
    if not target.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RarSupportError(
            "UnRAR installer finished without creating UnRAR.exe."
            + (f" {detail}" if detail else "")
        )
    try:
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    except OSError:
        pass
    sfx.unlink(missing_ok=True)
    return target
