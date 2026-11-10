# Architecture & Design Specifications: Jack's LML Companion

## 1. Core Modules & Data Flow

### A. Configuration & Startup (`app.py` & `infrastructure.py`)
- Reads/writes `config.json` to store the validated absolute path to the RDR2 root directory (where `RDR2.exe` resides).
- Performs a startup health check for the standard stack:
  - `ScriptHookRDR2.dll` from **ScriptHookRDR2 V2** (kepmehz / Nexus)
  - `dinput8.dll` from **Ultimate ASI Loader x64** (ThirteenAG)
  - `vfs.asi` from **Lenny's Mod Loader RDR** (`lml_rdr_beta_11.zip` via rdr2mods.com)
  - `ScriptHookRDRDotNet.asi` from **ScriptHookRDR2DotNet**
- When a package contains both x64 and Win32 ASI loaders, only the x64 copy is deployed.
- **Install missing infrastructure** auto-downloads Ultimate ASI Loader x64 and ScriptHookRDR2DotNet from GitHub, then guides a manual download for ScriptHookRDR2 V2 (Nexus) and Lenny's Mod Loader (rdr2mods.com). Manual steps keep the app in front: the user opens the download page from a button, then selects the archive. Quarantined binaries count as present.
- **Optional addon:** DLSSTweaks for RDR2 (`xinput9_1_0.dll`, `dlsstweaks.ini`, `DLSSTweaksConfig.exe`). Manual Nexus download of file “1. DLSSTweaks for RDR2”; offered during infrastructure install and via a dedicated button. After deploy, the UI can open `DLSSTweaksConfig.exe` so the user sets ForceDLAA, then reminds them to enable DLSS and zero sharpening in-game.
- RAR packages bootstrap a backend automatically (existing UnRAR/7-Zip, otherwise free UnRAR from rarlab.com into `tools/`).
- Triggers `diagnostics.py` to check for recent crash logs (`crash-main.log`) if a crash occurred on the previous session.

### B. Ingestion, XML Parsing & Normalization (`analyzer.py`)
- User selects or drops a `.zip` or `.rar` mod archive.
- Extracted to a temporary staging directory (`tmp_extract_<mod_name>`).
- **Metadata Parsing:** Scans the extracted tree for `install.xml` via `xml.etree.ElementTree` to extract mod name, author, and version.
- **With `install.xml`:** LML-aware routing. Custom assets go under `<game_dir>/lml/<mod_path>`; declared root scripts stay in the game root.
- **Without `install.xml`:** Treated as a manual mod. The UI can open a readme if present, then asks whether to install to the **game root** (preserve archive layout) or an **LML folder** (and only then generate a baseline `install.xml`).

### C. Collision Detection Engine (`collision.py`)
- Maps out incoming file target paths before copying bytes.
- Cross-references incoming files against active JSON manifests in `mod_manifests/`:
  - **Root Files:** Intercepts direct file overwrites (hard conflicts).
  - **LML Mod Folders:** Detects if an LML subfolder name already exists.
- Halts installation and prompts the user via the UI if a collision occurs.

### D. Manifest Tracking (`manifest.py`)
- Generates `mod_manifests/<mod_name>.json` containing:
  - `mod_name`: String identifier
  - `archive_source`: Original filename
  - `files`: Array of absolute paths written to disk

### E. Story / Online Mode Switcher (`profiles.py`)
- **Modded Story Mode:** Restores active LML hooks (`vfs.asi`), ASI loaders (`dinput8.dll`), and DLSSTweaks injectors.
- **Vanilla Online Mode:** Safely quarantines ASI loaders, LML virtual file system files (`.asi` → `.off`), and DLSSTweaks injectors (`xinput9_1_0.dll` / `nvngx.dll`), so online play does not load them.

---

## 2. Uninstallation Workflow
When a user selects a mod and clicks **Uninstall**:
1. The app loads `mod_manifests/<mod_name>.json`.
2. It iterates through the tracked `files` array and unlinks (deletes) each file from disk.
3. It traverses parent directories upward and safely removes empty directories.
4. It deletes the JSON manifest file and refreshes the UI list widget.