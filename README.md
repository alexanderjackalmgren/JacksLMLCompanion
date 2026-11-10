# Jack's LML Companion

**Jack's LML Companion** is a modern mod manager and installer wrapper for **Red Dead Redemption 2 (RDR2)**, built to replace Lenny's outdated official companion GUI (`ModManager.UI.exe`).

## Core Features
- **Foolproof Archive Ingestion:** Automatically normalizes messy `.zip` and `.rar` files, extracts LML assets, and parses `install.xml` metadata.
- **Manifest-Driven Clean Uninstalls:** Tracks every file written to disk via individual JSON manifests, guaranteeing zero orphaned files when removing mods.
- **File-Level Collision Detection:** Intercepts root-directory script conflicts and duplicate LML mod folders before they break your game.
- **Automated Infrastructure Manager:** Scans for and deploys the standard stack: **ScriptHookRDR2 V2**, **Ultimate ASI Loader x64**, **Lenny's Mod Loader RDR**, and **ScriptHookRDR2DotNet** (optional **DLSSTweaks** addon).
- **Crash Log Diagnostics:** Automatically inspects and parses RDR2 crash logs on startup to explain why a crash happened and how to fix it.
- **Story / Online Mode Toggle:** Instantly switch between **Modded Storymode** and **Disabled/Online Mode**, quarantining ASI loaders, root `.asi` plugins, and DLSSTweaks injectors so online play does not load them.

## Limitations
- **No per-mod enable/disable:** Installed mods are managed by install and uninstall only. There is no individual on/off toggle per mod; use the Story / Online mode switch to park loaders for online play.

## How to build / run without the executable

Use this if Windows or antivirus blocks the downloaded `.exe`.  
You will run the app with Python instead.

### 1. Install Python

1. Download **Python 3.10 or newer** from: https://www.python.org/downloads/
2. Run the installer.
3. **Important:** enable **Add python.exe to PATH**.
4. Finish the install.

Check that it worked. Open **PowerShell** or **Command Prompt** and run:

```text
py --version
```

You should see something like `Python 3.12.x`.

### 2. Get the source code

Download the project from GitHub:  
https://github.com/alexanderjackalmgren/JacksLMLCompanion

- Click **Code → Download ZIP**, then unzip it  
  **or**
- Clone the repo with git

Open a terminal in the project folder (the folder that contains `requirements.txt` and `src`).

Tip: in File Explorer, open that folder, click the address bar, type `powershell`, and press Enter.

### 3. Create a virtual environment

```powershell
py -3 -m venv venv
venv\Scripts\Activate.ps1
```

If activation is blocked, run this once, then try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

When it works, your prompt usually starts with `(venv)`.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Start the app

```powershell
python src/app.py
```

The window should open like the normal app. Config files are created in the project folder.

### Next time

1. Open the project folder in PowerShell  
2. Activate the environment:

```powershell
venv\Scripts\Activate.ps1
```

3. Start the app:

```powershell
python src/app.py
```

### Optional: build your own .exe

Only if you want a local executable. Antivirus may still flag PyInstaller builds.

```powershell
pip install pyinstaller
pyinstaller JacksLMLCompanion.spec
```

The executable will be in the `dist` folder as `JacksLMLCompanion-<version>.exe`.

### Notes

- Keep the `venv` folder. You do not need to recreate it every time.
- You still need your RDR2 folder and the usual mod tools (Script Hook, LML, etc.). This app helps install and manage them; it is not a replacement for the game.
- Running from source is the recommended path when the packaged executable is blocked.
Setup, tests, and packaging are in [docs/development.md](docs/development.md). System design is in [docs/architecture.md](docs/architecture.md).
