# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FDD Firmware Updater.

Build (from repo root):
  macOS:   pyinstaller installer/fdd_updater.spec
  Windows: pyinstaller installer\\fdd_updater.spec
"""

import platform
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# SPECPATH is the directory containing this spec file (installer/).
# The repo root is one level up.
REPO_ROOT = str(Path(SPECPATH).parent)

# Collect all resources (firmware UF2s, manifest, bundled tools)
added_files = [
    (str(Path(REPO_ROOT) / "resources"), "resources"),
]

# Explicitly collect mpremote and pyserial in full — they are called via
# sys.executable -m mpremote (subprocess) so PyInstaller won't find them
# through static import analysis alone.
for pkg in ("mpremote", "serial"):
    datas, binaries, hiddenimports = collect_all(pkg)
    added_files += datas

a = Analysis(
    [str(Path(REPO_ROOT) / "launcher.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        "hid",
        "serial",
        "serial.tools",
        "serial.tools.list_ports",
        *collect_submodules("mpremote"),
        *collect_submodules("serial"),
        "requests",
        "tkinter",
        "tkinter.ttk",
        "tkinter.scrolledtext",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="FDD Firmware Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No terminal window on Windows/macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,       # None = native arch; set "arm64" or "x86_64" to cross-compile
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FDD Firmware Updater",
)

# macOS: wrap in .app bundle
if platform.system() == "Darwin":
    app = BUNDLE(
        coll,
        name="FDD Firmware Updater.app",
        icon=None,              # Set to "installer/icon.icns" when available
        bundle_identifier="com.flightdeckdiy.fdd-firmware-updater",
        version="1.0.0",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
