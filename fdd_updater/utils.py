"""Platform helpers: resource path resolution, BOOTSEL volume detection."""

import os
import sys
import string
import platform
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Return the absolute path to a bundled resource.

    Works both when running from source and when packaged with PyInstaller
    (where sys._MEIPASS points to the temp extraction directory).
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent
    return base / "resources" / relative


def find_bootsel_volume() -> Path | None:
    """Return the path to the mounted BOOTSEL mass-storage volume, or None."""
    system = platform.system()
    if system == "Darwin":
        for name in ("RPI-RP2", "RP2350"):
            p = Path("/Volumes") / name
            if p.exists() and (p / "INFO_UF2.TXT").exists():
                return p
        # Also check case variants macOS may use
        volumes = Path("/Volumes")
        if volumes.exists():
            for entry in volumes.iterdir():
                if entry.name.upper() in ("RPI-RP2", "RP2350") and (entry / "INFO_UF2.TXT").exists():
                    return entry
        return None
    elif system == "Windows":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists() and (drive / "INFO_UF2.TXT").exists():
                return drive
        return None
    else:
        # Linux fallback
        for mount_root in (Path("/media"), Path("/mnt")):
            if not mount_root.exists():
                continue
            for user_dir in mount_root.iterdir():
                for entry in user_dir.iterdir() if user_dir.is_dir() else []:
                    if entry.name.upper() in ("RPI-RP2", "RP2350") and (entry / "INFO_UF2.TXT").exists():
                        return entry
        return None


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_macos() -> bool:
    return platform.system() == "Darwin"
