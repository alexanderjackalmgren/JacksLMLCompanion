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

`.rar` extraction needs the `rarfile` package and an UnRAR executable on `PATH`. Zip archives use the standard library.

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
PyInstaller is a build tool and is not part of the runtime requirements.

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --name "JacksLMLCompanion" --hidden-import rarfile --hidden-import requests src/app.py
```

The executable is written to `dist/JacksLMLCompanion.exe`.

Config, `mod_manifests/`, and staging data are stored beside that executable. In a source checkout they are stored in the project root.

## Runtime files
Do not commit `config.json`, `profile_state.json`, `mod_manifests/`, or `staging/`. The app creates them on the machine that runs it.
