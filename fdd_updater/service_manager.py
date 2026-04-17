"""Windows service management for FlightDeckConnect services.

On macOS this module is a no-op — all public functions return immediately.
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

from .utils import is_windows

_SERVICES = ("FlightDeckConnectService", "FlightDeckConnectHID")
_SERVICE_POLL_INTERVAL = 0.5
_SERVICE_STOP_TIMEOUT = 20.0
_SERVICE_START_TIMEOUT = 20.0


def stop_services(log: Callable[[str], None] | None = None) -> None:
    """Stop FlightDeckConnect and FlightDeckConnectHID services (Windows only)."""
    if not is_windows():
        return
    for name in _SERVICES:
        _sc("stop", name, log)
        _wait_for_service_state(name, "STOPPED", _SERVICE_STOP_TIMEOUT, log)


def start_services(log: Callable[[str], None] | None = None) -> None:
    """Start FlightDeckConnect and FlightDeckConnectHID services (Windows only)."""
    if not is_windows():
        return
    for name in _SERVICES:
        _sc("start", name, log)
        _wait_for_service_state(name, "RUNNING", _SERVICE_START_TIMEOUT, log)


def _sc(action: str, service: str, log: Callable[[str], None] | None) -> None:
    def _log(msg: str) -> None:
        if log:
            log(msg)

    verb = "Stopping" if action == "stop" else "Starting" if action == "start" else action.capitalize()
    _log(f"{verb} service: {service}")
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


def _wait_for_service_state(
    service: str,
    target_state: str,
    timeout: float,
    log: Callable[[str], None] | None,
) -> None:
    """Wait until sc.exe reports a target state, without failing the update flow."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    deadline = time.monotonic() + timeout
    last_state: str | None = None
    while time.monotonic() < deadline:
        state = _query_service_state(service)
        if state is None:
            return
        last_state = state
        if state == target_state:
            return
        time.sleep(_SERVICE_POLL_INTERVAL)

    if last_state:
        _log(f"  {service}: still {last_state} after {timeout:.0f}s")


def _query_service_state(service: str) -> str | None:
    """Return the service state name reported by sc.exe, or None if unavailable."""
    try:
        result = subprocess.run(
            ["sc", "query", service],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None

    output = result.stdout or result.stderr or ""
    if result.returncode != 0:
        return None

    for line in output.splitlines():
        if "STATE" not in line:
            continue
        parts = line.split()
        if parts:
            return parts[-1].upper()
    return None
