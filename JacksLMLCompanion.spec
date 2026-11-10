# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Jack's LML Companion."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
SRC = ROOT / "src"

pyqt_datas, pyqt_binaries, pyqt_hiddenimports = collect_all("PyQt6")

datas = [
    (str(ROOT / "assets" / "app_icon.ico"), "assets"),
    (str(ROOT / "assets" / "app_icon.png"), "assets"),
    (str(ROOT / "assets" / "library_hero_storymode.tif"), "assets"),
    (str(ROOT / "assets" / "library_hero_onlinemode.tif"), "assets"),
]
datas += pyqt_datas

a = Analysis(
    [str(SRC / "app.py")],
    pathex=[str(SRC)],
    binaries=pyqt_binaries,
    datas=datas,
    hiddenimports=["rarfile", "requests", *pyqt_hiddenimports],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="JacksLMLCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app_icon.ico"),
)
