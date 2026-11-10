"""Read a fresh RDR2 crash log and map known loader failures to a next step."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiagnosticFinding:
    code: str
    severity: str
    title: str
    detail: str
    suggestion: str
    log_path: Path | None = None


@dataclass(frozen=True)
class _Rule:
    code: str
    title: str
    suggestion: str
    needles: tuple[str, ...]


_RULES = (
    _Rule(
        code="scripthook_version",
        title="ScriptHookRDR2 V2 version mismatch",
        suggestion=(
            "Update ScriptHookRDR2.dll from ScriptHookRDR2 V2 so it matches the installed game version."
        ),
        needles=("scripthook", "version"),
    ),
    _Rule(
        code="scripthook_unsupported",
        title="ScriptHookRDR2 V2 does not support this game build",
        suggestion=(
            "Update ScriptHookRDR2 V2, or wait for a release that supports the current game patch."
        ),
        needles=("scripthook", "unsupported"),
    ),
    _Rule(
        code="vfs_injection",
        title="VFS injection failure",
        suggestion=(
            "Reinstall Lenny's Mod Loader so vfs.asi matches ScriptHookRDR2 V2 and the game version."
        ),
        needles=("vfs", "fail"),
    ),
    _Rule(
        code="vfs_error",
        title="VFS injection failure",
        suggestion=(
            "Reinstall Lenny's Mod Loader so vfs.asi matches ScriptHookRDR2 V2 and the game version."
        ),
        needles=("vfs.asi", "error"),
    ),
)


class CrashDiagnostics:
    """Inspect ``crash-main.log`` in the game folder or the Rockstar documents folder."""

    def inspect(self, game_dir: Path) -> list[DiagnosticFinding]:
        log_path = self.locate_log(game_dir)
        if log_path is None:
            return [
                DiagnosticFinding(
                    code="no_log",
                    severity="info",
                    title="No crash log found",
                    detail="crash-main.log was not in the game folder or the Rockstar documents folder.",
                    suggestion="If the game just crashed, launch it once so the log can be written, then scan again.",
                )
            ]
        return self.parse(_read_text(log_path), log_path)

    def locate_log(self, game_dir: Path) -> Path | None:
        documents = Path.home() / "Documents" / "Rockstar Games" / "Red Dead Redemption 2"
        candidates = [game_dir / "crash-main.log", documents / "crash-main.log"]
        existing = [path for path in candidates if path.is_file()]
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    def parse(self, text: str, log_path: Path | None = None) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        seen: set[str] = set()
        for line in text.splitlines():
            lowered = line.casefold()
            for rule in _RULES:
                if rule.code in seen:
                    continue
                if all(needle in lowered for needle in rule.needles):
                    seen.add(rule.code)
                    findings.append(
                        DiagnosticFinding(
                            code=rule.code,
                            severity="warning",
                            title=rule.title,
                            detail=line.strip()[:500],
                            suggestion=rule.suggestion,
                            log_path=log_path,
                        )
                    )
        if findings:
            return findings
        return [
            DiagnosticFinding(
                code="no_match",
                severity="info",
                title="No known loader failure in the latest crash log",
                detail=(
                    str(log_path)
                    if log_path
                    else "The log did not match a ScriptHookRDR2 V2 or VFS rule."
                ),
                suggestion="Check the mod that was added last, then scan again after the next crash.",
                log_path=log_path,
            )
        ]


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")
