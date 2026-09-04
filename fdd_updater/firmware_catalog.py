"""Firmware catalog: load manifest.json and optionally check for updates on GitHub."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .utils import is_dev_mode, resource_path


@dataclass
class FirmwareEntry:
    id: str
    name: str
    version: str
    firmware_type: str       # "hid" or "cdc"
    uf2: str                 # Relative path within resources/firmware/
    app_files: list[str]     # Relative paths for extra .py files (cdc only)
    description: str
    dev_only: bool = False   # Hidden unless FDD_UPDATER_DEV is set

    def uf2_path(self) -> Path:
        return resource_path(f"firmware/{self.uf2}")

    def app_file_paths(self) -> list[Path]:
        return [resource_path(f"firmware/{f}") for f in self.app_files]

    def __str__(self) -> str:
        return f"{self.name}  v{self.version}"


@dataclass
class FirmwareCatalog:
    entries: list[FirmwareEntry] = field(default_factory=list)
    github_releases_url: str = ""
    manifest_version: int = 1

    def by_id(self, fw_id: str) -> FirmwareEntry | None:
        for e in self.entries:
            if e.id == fw_id:
                return e
        return None


def load_catalog() -> FirmwareCatalog:
    """Load the bundled manifest.json."""
    manifest_path = resource_path("firmware/manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    entries = [
        FirmwareEntry(
            id=fw["id"],
            name=fw["name"],
            version=fw["version"],
            firmware_type=fw["type"],
            uf2=fw["uf2"],
            app_files=fw.get("app_files", []),
            description=fw.get("description", ""),
            dev_only=bool(fw.get("dev_only", False)),
        )
        for fw in data.get("firmware", [])
    ]

    # Dev-only images stay out of the picker entirely: the combo box and
    # _selected_firmware() index into this same list, so filtering here keeps
    # the two in step.
    if not is_dev_mode():
        entries = [e for e in entries if not e.dev_only]

    return FirmwareCatalog(
        entries=entries,
        github_releases_url=data.get("github_releases_url", ""),
        manifest_version=data.get("manifest_version", 1),
    )


def check_for_updates(
    catalog: FirmwareCatalog,
    log: Callable[[str], None] | None = None,
) -> tuple[bool, str, str]:
    """Check GitHub releases for a newer version of the updater app.

    Returns (update_available, latest_version_string, asset_download_url).
    asset_download_url is the platform-appropriate installer/DMG URL, or "" if none found.
    """
    if not catalog.github_releases_url:
        return False, "", ""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    try:
        import platform
        import requests  # type: ignore
        _log(f"Checking for updates at {catalog.github_releases_url} ...")
        resp = requests.get(catalog.github_releases_url, timeout=8)
        resp.raise_for_status()
        release = resp.json()
        tag = release.get("tag_name", "").lstrip("v")
        if not tag:
            _log("No version tag found in release.")
            return False, "", ""

        from fdd_updater import __version__
        current = _parse_version(__version__)
        latest = _parse_version(tag)

        system = platform.system()
        asset_url = _pick_asset(release.get("assets", []), system)

        if latest > current:
            _log(f"Update available: v{tag}  (current: v{__version__})")
            return True, tag, asset_url
        _log(f"Already up to date (v{__version__}).")
        return False, tag, asset_url

    except Exception as exc:
        _log(f"Update check failed: {exc}")
        return False, "", ""


def _pick_asset(assets: list[dict], system: str) -> str:
    """Return the browser_download_url for the best asset for this platform."""
    if system == "Darwin":
        for asset in assets:
            if asset.get("name", "").lower().endswith(".dmg"):
                return asset.get("browser_download_url", "")
        return ""

    if system == "Windows":
        # A release carries both the portable one-file EXE and the Inno Setup
        # installer. The auto-updater replaces the running binary in place, so
        # it must get the portable EXE — handing it the installer would swap the
        # app for a setup stub. Prefer non-installer assets; fall back to any
        # EXE/MSI so a release that only ships an installer still updates (via
        # the run-the-installer path in _apply_update_windows).
        candidates = [
            (a.get("name", "").lower(), a.get("browser_download_url", ""))
            for a in assets
            if a.get("name", "").lower().endswith((".exe", ".msi"))
        ]
        for name, url in candidates:
            if "setup" not in name and "install" not in name:
                return url
        return candidates[0][1] if candidates else ""

    return ""


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)
