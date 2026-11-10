JacksLMLCompanion/
├── .cursorrules
├── .gitignore
├── README.md
├── requirements.txt
├── JacksLMLCompanion.spec     # PyInstaller one-file build
├── Project Directory Structure.md
├── assets/
│   ├── app_icon.ico
│   ├── app_icon.png
│   ├── library_hero_storymode.tif
│   └── library_hero_onlinemode.tif
├── docs/
│   ├── additional.md
│   ├── architecture.md
│   └── development.md
├── src/
│   ├── __init__.py
│   ├── app.py                 # PyQt6 entry point and startup checks
│   ├── core/
│   │   ├── __init__.py
│   │   ├── analyzer.py        # Archive extraction, normalization, install.xml
│   │   ├── collision.py       # Root-script and LML-folder collision checks
│   │   ├── diagnostics.py     # crash-main.log forensics
│   │   ├── infrastructure.py  # Game-folder validation and core binary deploy
│   │   ├── manifest.py        # JSON manifests and clean uninstall
│   │   └── profiles.py        # Modded Story / Vanilla Online mode switch
│   └── ui/
│       ├── __init__.py
│       └── main_window.py
└── tests/
    └── test_core.py
