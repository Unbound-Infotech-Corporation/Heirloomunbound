# Heirloom — PyInstaller spec
# Produces a single-folder Windows app at dist/Heirloom/Heirloom.exe.
# Single-folder is preferred over --onefile because:
#   • startup is ~5x faster (no temp-extract on every launch)
#   • SmartScreen tends to be less hostile to multi-file apps
#   • PySide6's Qt plugins live as files anyway — no benefit to bundling
#
# Build on Windows:
#     pip install -r requirements.txt pyinstaller
#     pyinstaller heirloom.spec --clean --noconfirm
#
# Output:  dist\Heirloom\Heirloom.exe (double-click to launch)
# Then zip dist\Heirloom\ for distribution.

# ruff: noqa: F821 -- this file is executed by PyInstaller; `Analysis`/`PYZ`/etc. are injected
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# PySide6 multimedia + svg need explicit hidden imports — PyInstaller's
# heuristic misses some Qt plugins.
hiddenimports = (
    collect_submodules("PySide6.QtMultimedia")
    + collect_submodules("PySide6.QtMultimediaWidgets")
    + ["sounddevice", "soundfile", "numpy"]
)

datas: list = []  # add any non-Python assets here later (icons, fonts, etc.)

a = Analysis(
    ["heirloom/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Strip the parts of PySide6 we never use to shrink the bundle.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtQuick3D",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Heirloom",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                # safe: UPX shrinks the exe ~30% with no startup cost
    console=False,           # GUI app — no console window
    disable_windowed_traceback=False,
    icon=None,               # supply Heirloom.ico here when we have one
    version=None,            # supply version_info.txt for File Properties
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        # UPX corrupts some Qt plugin DLLs — exclude the ones known to break.
        "Qt6Core.dll",
        "Qt6Network.dll",
        "Qt6Multimedia.dll",
    ],
    name="Heirloom",
)
