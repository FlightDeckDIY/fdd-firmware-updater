"""Windows service management for FlightDeckConnect services.

On macOS this module is a no-op — all public functions return immediately.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

from .utils import is_windows

_SERVICES = ("FlightDeckConnect", "FlightDeckConnectHID")


def stop_services(log: Callable[[str], None] | None = None) -> None:
    """Stop FlightDeckConnect and FlightDeckConnectHID services (Windows only)."""
    if not is_windows():
        return
    for name in _SERVICES:
        _sc("stop", name, log)
    # Brief pause to let the service release COM ports / HID handles
    time.sleep(1.5)


def start_services(log: Callable[[str], None] | None = None) -> None:
    """Start FlightDeckConnect and FlightDeckConnectHID services (Windows only)."""
    if not is_windows():
        return
    for name in _SERVICES:
        _sc("start", name, log)


def _sc(action: str, service: str, log: Callable[[str], None] | None) -> None:
    def _log(msg: str) -> None:
        if log:
            log(msg)

    _log(f"{action.capitalize()}ping service: {service}")
    try:
        result = subprocess.run(
            ["sc", action, service],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            _log(f"  {service}: {action} OK")
        else:
            # Error 1060 = service does not exist; 1062 = not running (stop)
            # Both are acceptable — log but don't raise.
            stderr = (result.stderr or result.stdout or "").strip()
            _log(f"  {service}: {action} returned {result.returncode} — {stderr}")
    except FileNotFoundError:
        _log("  sc.exe not found — skipping service management")
    except subprocess.TimeoutExpired:
        _log(f"  {service}: {action} timed out")
    except Exception as exc:
        _log(f"  {service}: {action} error — {exc}")
