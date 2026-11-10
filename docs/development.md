# Development & Packaging Guide: Jack's LML Companion

## Setup
1. Clone or open the repository.
2. Create and activate a virtual environment.

Windows (PowerShell):

```powershell
py -3 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS and Linux:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`.rar` extraction uses the `rarfile` package plus a backend tool. The app prefers an existing UnRAR or 7-Zip install; on Windows it can download RARLAB's free UnRAR into `tools/` automatically. Zip archives use the standard library.

Infrastructure auto-download covers Ultimate ASI Loader x64 and ScriptHookRDR2DotNet only. ScriptHookRDR2 V2 and Lenny's Mod Loader stay manual because Nexus and rdr2mods CDN links are not stably automatable.

## Run
From the project root:

```bash
python src/app.py
```

## Tests
File routing, collision checks, uninstall, and profile quarantine are covered without opening the window:

```bash
python -m unittest tests.test_core -v
```

## Package
PyInstaller is a build tool and is not part of the runtime requirements. From the project root:

```powershell
pip install pyinstaller
pyinstaller JacksLMLCompanion.spec
```

The one-file, no-console executable is written to `dist/JacksLMLCompanion.exe`. The spec bundles `assets/` (app icon + Story/Online banners) and PyQt6 image plugins so TIFF banners load in the frozen build.

Config, `mod_manifests/`, `cache/`, `tools/`, and staging data are stored beside that executable. In a source checkout they are stored in the project root.

## Runtime files
Do not commit `config.json`, `profile_state.json`, `mod_manifests/`, `staging/`, or `cache/`. The app creates them on the machine that runs it.
