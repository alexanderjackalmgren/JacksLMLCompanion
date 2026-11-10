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

## Development
From a virtual environment at the project root:

```bash
pip install -r requirements.txt
python src/app.py
```

Setup, tests, and packaging are in [docs/development.md](docs/development.md). System design is in [docs/architecture.md](docs/architecture.md).
