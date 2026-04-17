"""Core firmware update logic.

Update flow:
  1. Stop Windows services
  2. Enter BOOTSEL mode (HID command or mpremote bootsel)
  3. Wait for BOOTSEL volume to mount
  4. Copy UF2 to BOOTSEL volume
  5. Wait for device to re-enumerate in target mode
  6. Upload MicroPython .py files (CDC target only)
  7. Restart Windows services

All progress is reported via a callback so this module has no GUI dependency.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from .device_detector import DeviceType, FoundDevice
from .firmware_catalog import FirmwareEntry
from .service_manager import start_services, stop_services
from .utils import find_bootsel_volume

# HID bootsel report constants (from G1000_HID/tools/enter_boot.py)
_HID_VID = 0x2E8A
_HID_PID = 0x10F7
_REPORT_ID_DEVICE_CTL = 0x12
_DEVICE_CTL_ENTER_BOOT = 0x02
_REPORT_SIZE = 32

# Timeouts
_BOOTSEL_POLL_INTERVAL = 0.5   # seconds between polls
_BOOTSEL_TIMEOUT = 30.0        # seconds to wait for BOOTSEL volume
_REBOOT_POLL_INTERVAL = 0.75
_REBOOT_TIMEOUT = 30.0


class UpdateError(Exception):
    """Raised when a firmware update step fails."""


def flash_firmware(
    device: FoundDevice,
    firmware: FirmwareEntry,
    log: Callable[[str], None],
    progress: Callable[[int], None],
) -> None:
    """Perform a complete firmware update.

    Args:
        device:   The target device (HID, CDC, or BOOTSEL).
        firmware: The firmware to install.
        log:      Callback for log messages.
        progress: Callback for progress percentage (0-100).
    """
    log(f"Starting update: {firmware.name} v{firmware.version}")
    log(f"Target device: {device.label}")

    # Verify UF2 exists
    uf2_path = firmware.uf2_path()
    if not uf2_path.exists():
        raise UpdateError(f"UF2 file not found: {uf2_path}")

    progress(5)

    # Step 1: Stop Windows services
    stop_services(log)
    progress(10)

    try:
        # Step 2: Enter BOOTSEL if not already there
        if device.device_type == DeviceType.BOOTSEL:
            log("Device is already in BOOTSEL mode.")
            bootsel_vol = find_bootsel_volume()
            if bootsel_vol is None:
                raise UpdateError("BOOTSEL volume not found even though device appeared to be in BOOTSEL mode.")
        else:
            bootsel_vol = _enter_bootsel(device, log)

        progress(35)

        # Step 3: Copy UF2
        _copy_uf2(uf2_path, bootsel_vol, log)
        progress(60)

        # Step 4: Wait for device to reboot into target mode
        log("Waiting for device to reboot...")
        _wait_for_reboot(firmware, log)
        progress(80)

        # Step 5: Upload MicroPython app files if target is CDC
        if firmware.firmware_type == "cdc" and firmware.app_files:
            _upload_micropython_files(firmware, log)

        progress(100)
        log("Firmware update complete!")

    finally:
        # Always restart services even if update failed
        start_services(log)


# ---------------------------------------------------------------------------
# Internal steps
# ---------------------------------------------------------------------------

def _enter_bootsel(device: FoundDevice, log: Callable[[str], None]) -> Path:
    """Send the BOOTSEL command to the device and wait for the volume to mount."""
    if device.device_type == DeviceType.HID:
        _hid_enter_bootsel(device, log)
    elif device.device_type == DeviceType.CDC:
        _cdc_enter_bootsel(device, log)
    else:
        raise UpdateError(f"Cannot enter BOOTSEL for device type: {device.device_type}")

    log("Waiting for BOOTSEL volume to mount...")
    vol = _poll_for_bootsel_volume()
    if vol is None:
        raise UpdateError(
            f"BOOTSEL volume did not appear within {_BOOTSEL_TIMEOUT:.0f}s. "
            "Check that the device is connected and try again."
        )
    log(f"BOOTSEL volume found: {vol}")
    return vol


def _hid_enter_bootsel(device: FoundDevice, log: Callable[[str], None]) -> None:
    """Send DEVICE_CTL: ENTER_BOOT over HID."""
    log("Sending BOOTSEL command via HID...")
    try:
        import hid  # type: ignore
    except ImportError as exc:
        raise UpdateError(
            "Python 'hid' library not installed. Run: pip install hid"
        ) from exc

    dev = hid.device()
    try:
        if device.hid_path:
            dev.open_path(device.hid_path)
        else:
            dev.open(_HID_VID, _HID_PID)
    except Exception as exc:
        raise UpdateError(f"Could not open HID device: {exc}") from exc

    report = [_REPORT_ID_DEVICE_CTL, _DEVICE_CTL_ENTER_BOOT] + [0x00] * (_REPORT_SIZE - 2)
    try:
        dev.write(report)
        log("  BOOTSEL command sent.")
    except Exception as exc:
        raise UpdateError(f"Failed to send HID BOOTSEL report: {exc}") from exc
    finally:
        dev.close()

    # Brief pause — device needs a moment to reset
    time.sleep(1.0)


def _cdc_enter_bootsel(device: FoundDevice, log: Callable[[str], None]) -> None:
    """Use mpremote to put MicroPython device into BOOTSEL mode."""
    if device.port is None:
        raise UpdateError("CDC device has no serial port path.")

    log(f"Sending BOOTSEL command via mpremote ({device.port})...")
    # allow_nonzero=True: device disconnects mid-command, mpremote exits non-zero — that's expected
    _run_mpremote(["connect", device.port, "bootloader"], log, allow_nonzero=True)
    time.sleep(1.0)


def _copy_uf2(uf2_path: Path, volume: Path, log: Callable[[str], None]) -> None:
    """Copy the UF2 file to the BOOTSEL mass-storage volume."""
    dest = volume / uf2_path.name
    log(f"Copying {uf2_path.name} to {volume} ...")
    try:
        shutil.copy2(str(uf2_path), str(dest))
        log("  UF2 copied. Device will flash and reboot automatically.")
    except Exception as exc:
        raise UpdateError(f"Failed to copy UF2: {exc}") from exc


def _wait_for_reboot(firmware: FirmwareEntry, log: Callable[[str], None]) -> None:
    """Wait for the BOOTSEL volume to disappear (device rebooted after flash)."""
    deadline = time.monotonic() + _REBOOT_TIMEOUT
    while time.monotonic() < deadline:
        if find_bootsel_volume() is None:
            log("  Device rebooted.")
            # Give the OS a moment to enumerate the new device
            time.sleep(2.0)
            return
        time.sleep(_REBOOT_POLL_INTERVAL)
    # If volume is still there after timeout, the flash may have failed
    log("  Warning: BOOTSEL volume still mounted after timeout. Flash may not have completed.")


def _upload_micropython_files(
    firmware: FirmwareEntry,
    log: Callable[[str], None],
) -> None:
    """Upload MicroPython .py files to the device via mpremote."""
    from .device_detector import scan_devices, DeviceType

    log("Waiting for MicroPython CDC device to enumerate...")
    deadline = time.monotonic() + _REBOOT_TIMEOUT
    cdc_port: str | None = None
    while time.monotonic() < deadline:
        devices = scan_devices()
        cdc_devices = [d for d in devices if d.device_type == DeviceType.CDC]
        if cdc_devices:
            cdc_port = cdc_devices[0].port
            log(f"  Device found at {cdc_port}")
            break
        time.sleep(_REBOOT_POLL_INTERVAL)

    if cdc_port is None:
        raise UpdateError(
            "MicroPython device did not enumerate in time. "
            "You can upload files manually with: mpremote connect <port> cp *.py :"
        )

    file_paths = firmware.app_file_paths()
    if not file_paths:
        return

    log(f"Uploading {len(file_paths)} application file(s) via mpremote...")
    # "resume" skips mpremote's automatic soft-reset so we don't race with main.py restarting.
    # "cp <files> :" copies all files to the root of the device filesystem.
    _run_mpremote(
        ["connect", cdc_port, "resume", "cp"] + [str(p) for p in file_paths] + [":"],
        log,
    )
    log("  Application files uploaded.")


def _poll_for_bootsel_volume() -> Path | None:
    """Poll until BOOTSEL volume appears or timeout."""
    deadline = time.monotonic() + _BOOTSEL_TIMEOUT
    while time.monotonic() < deadline:
        vol = find_bootsel_volume()
        if vol is not None:
            return vol
        time.sleep(_BOOTSEL_POLL_INTERVAL)
    return None


def _run_mpremote(
    args: list[str],
    log: Callable[[str], None],
    allow_nonzero: bool = False,
) -> None:
    """Run mpremote via its Python API.

    Works both when running from source and inside a PyInstaller bundle.
    PyInstaller frozen binaries don't support `sys.executable -m module`,
    so we call mpremote.main.main() directly after patching sys.argv.
    """
    import io
    from contextlib import redirect_stdout, redirect_stderr

    old_argv = sys.argv[:]
    sys.argv = ["mpremote"] + args
    exit_code: int = 0

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        import mpremote.main  # type: ignore
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            mpremote.main.main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    except Exception as exc:
        raise UpdateError(f"mpremote error: {exc}") from exc
    finally:
        sys.argv = old_argv

    for line in stdout_buf.getvalue().splitlines():
        if line.strip():
            log(f"  {line}")
    for line in stderr_buf.getvalue().splitlines():
        if line.strip():
            log(f"  {line}")

    if not allow_nonzero and exit_code not in (0, None):
        err_out = (stderr_buf.getvalue() or stdout_buf.getvalue()).strip()
        raise UpdateError(f"mpremote failed (exit {exit_code}): {err_out}")
