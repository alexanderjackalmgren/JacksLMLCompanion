# Architecture & Design Specifications: Jack's LML Companion

## 1. Core Modules & Data Flow

### A. Configuration & Startup (`app.py` & `infrastructure.py`)
- Reads/writes `config.json` to store the validated absolute path to the RDR2 root directory (where `RDR2.exe` resides).
- Performs a startup health check for the standard stack:
  - `ScriptHookRDR2.dll` from **ScriptHookRDR2 V2** (kepmehz / Nexus)
  - `dinput8.dll` from **Ultimate ASI Loader x64** (ThirteenAG)
  - `vfs.asi` from **Lenny's Mod Loader RDR** (`lml_rdr_beta_11.zip` via rdr2mods.com)
  - `ScriptHookRDRDotNet.asi` from **ScriptHookRDR2DotNet 1.0.5.5**
- When a package contains both x64 and Win32 ASI loaders, only the x64 copy is deployed.
- Triggers `diagnostics.py` to check for recent crash logs (`crash-main.log`) if a crash occurred on the previous session.

### B. Ingestion, XML Parsing & Normalization (`analyzer.py`)
- User selects or drops a `.zip` or `.rar` mod archive.
- Extracted to a temporary staging directory (`tmp_extract_<mod_name>`).
- **Metadata Parsing:** Scans the extracted tree for `install.xml` via `xml.etree.ElementTree` to extract mod name, author, and version. If missing, auto-generates a baseline structure.
- **Heuristic Routing:**
  - **LML Routing:** Routes custom assets into `<game_dir>/lml/<mod_path>`.
  - **Root Scripts:** Routes `.asi`, `.dll`, or `.ini` files directly to `<game_dir>/`.

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

### E. Virtual Profiles & RedM Switcher (`profiles.py`)
- **Modded Story Mode:** Restores active LML hooks (`vfs.asi`), renames ASI loaders back to active extensions (`dinput8.dll`), and loads active mod manifests.
- **Vanilla Online Mode:** Safely quarantines ASI loaders and LML virtual file system files (`.asi` $\rightarrow$ `.off`), ensuring zero risk of triggering Rockstar's anti-cheat.
- **RedM Mode:** Ensures single-player script loaders are safely disabled and links base game assets to the RedM client configuration.

---

## 2. Uninstallation Workflow
When a user selects a mod and clicks **Uninstall**:
1. The app loads `mod_manifests/<mod_name>.json`.
2. It iterates through the tracked `files` array and unlinks (deletes) each file from disk.
3. It traverses parent directories upward and safely removes empty directories.
4. It deletes the JSON manifest file and refreshes the UI list widget.