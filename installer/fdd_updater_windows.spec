# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FDD Firmware Updater — Windows one-file build.

Produces a single self-contained EXE suitable for auto-update distribution.

Build (from repo root):
  pyinstaller installer\\fdd_updater_windows.spec --clean --noconfirm
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

REPO_ROOT = str(Path(SPECPATH).parent)

added_files = [
    (str(Path(REPO_ROOT) / "resources"), "resources"),
]

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

_icon = str(Path(SPECPATH) / "FDD_logo.ico")

# One-file: binaries, zipfiles, and datas all go directly into the EXE.
# UPX is disabled to avoid Windows Defender false positives.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="FDD Firmware Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
