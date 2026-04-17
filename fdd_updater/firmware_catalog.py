"""Firmware catalog: load manifest.json and optionally check for updates on GitHub."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .utils import resource_path


@dataclass
class FirmwareEntry:
    id: str
    name: str
    version: str
    firmware_type: str       # "hid" or "cdc"
    uf2: str                 # Relative path within resources/firmware/
    app_files: list[str]     # Relative paths for extra .py files (cdc only)
    description: str

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
        )
        for fw in data.get("firmware", [])
    ]

    return FirmwareCatalog(
        entries=entries,
        github_releases_url=data.get("github_releases_url", ""),
        manifest_version=data.get("manifest_version", 1),
    )


def check_for_updates(
    catalog: FirmwareCatalog,
    log: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Check GitHub releases for a newer version of the updater app.

    Returns (update_available, latest_version_string).
    """
    if not catalog.github_releases_url:
        return False, ""

    def _log(msg: str) -> None:
        if log:
            log(msg)

    try:
        import requests  # type: ignore
        _log(f"Checking for updates at {catalog.github_releases_url} ...")
        resp = requests.get(catalog.github_releases_url, timeout=8)
        resp.raise_for_status()
        release = resp.json()
        tag = release.get("tag_name", "").lstrip("v")
        if not tag:
            _log("No version tag found in release.")
            return False, ""

        from fdd_updater import __version__
        current = _parse_version(__version__)
        latest = _parse_version(tag)
        if latest > current:
            _log(f"Update available: v{tag}  (current: v{__version__})")
            return True, tag
        _log(f"Already up to date (v{__version__}).")
        return False, tag

    except Exception as exc:
        _log(f"Update check failed: {exc}")
        return False, ""


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)
