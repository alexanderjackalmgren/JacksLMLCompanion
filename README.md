# Jack's LML Companion

**Jack's LML Companion** is a modern, feature-rich mod manager and installer wrapper for **Red Dead Redemption 2 (RDR2)** and **RedM**, built to completely replace Lenny's outdated official companion GUI (`ModManager.UI.exe`).

## Core Features
- **Foolproof Archive Ingestion:** Automatically normalizes messy `.zip` and `.rar` files, extracts LML assets, and parses `install.xml` metadata.
- **Manifest-Driven Clean Uninstalls:** Tracks every file written to disk via individual JSON manifests, guaranteeing zero orphaned files when removing mods.
- **File-Level Collision Detection:** Intercepts root-directory script conflicts and duplicate LML mod folders before they break your game.
- **Automated Infrastructure Manager:** Scans for and deploys the standard stack: **ScriptHookRDR2 V2**, **Ultimate ASI Loader x64**, **Lenny's Mod Loader RDR**, and **ScriptHookRDR2DotNet 1.0.5.5**.
- **Crash Log Diagnostics:** Automatically inspects and parses RDR2 crash logs on startup to explain why a crash happened and how to fix it.
- **3-Way Profile & RedM Switcher:** Instantly toggle between **Modded Story Mode**, **Vanilla Online Mode** (quarantining loaders to prevent bans), and **RedM** integration from a single launcher dashboard.

## Development
From a virtual environment at the project root:

```bash
pip install -r requirements.txt
python src/app.py
```

Setup, tests, and packaging are in [docs/development.md](docs/development.md). System design is in [docs/architecture.md](docs/architecture.md).