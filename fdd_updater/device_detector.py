"""USB device discovery for FDD G1000 devices.

Detects three possible device states:
  - HID   : C/C++ firmware running, enumerated as USB HID (VID=0x2E8A, PID=0x10F7)
  - CDC   : MicroPython firmware running, enumerated as USB CDC serial port (VID=0x2E8A)
  - BOOTSEL: Device in bootloader mode, enumerated as USB mass-storage (RPI-RP2 / RP2350)
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from enum import Enum, auto

from .utils import find_bootsel_volume

# G1000 HID firmware USB identifiers
G1000_VID = 0x2E8A
G1000_PID = 0x10F7

# Raspberry Pi / RP2 VID used in both HID and CDC modes
RP_VID = 0x2E8A


class DeviceType(Enum):
    HID = auto()      # C/C++ HID firmware
    CDC = auto()      # MicroPython CDC firmware
    BOOTSEL = auto()  # Bootloader mass-storage mode
    UNKNOWN = auto()


@dataclass
class FoundDevice:
    device_type: DeviceType
    label: str                    # Human-readable display string
    port: str | None = None       # Serial port path (CDC only)
    hid_path: bytes | None = None # HID device path (HID only)
    vid: int = 0
    pid: int = 0
    serial_number: str = ""
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return self.label


def scan_devices() -> list[FoundDevice]:
    """Scan for all connected FDD G1000 devices in any state."""
    devices: list[FoundDevice] = []

    # 1. Check BOOTSEL first (takes priority — device may be mid-flash)
    bootsel_vol = find_bootsel_volume()
    if bootsel_vol is not None:
        devices.append(FoundDevice(
            device_type=DeviceType.BOOTSEL,
            label=f"G1000 [BOOTSEL] — {bootsel_vol}",
            extra={"volume": str(bootsel_vol)},
        ))

    # 2. Scan for HID devices
    devices.extend(_scan_hid())

    # 3. Scan for CDC devices
    devices.extend(_scan_cdc())

    return devices


def _scan_hid() -> list[FoundDevice]:
    """Return HID devices matching G1000 VID/PID."""
    try:
        import hid  # type: ignore
    except Exception:
        return []

    found: list[FoundDevice] = []
    try:
        device_list = hid.enumerate(G1000_VID, G1000_PID)
    except Exception:
        return []

    seen_paths: set[bytes] = set()
    for info in device_list:
        path = info.get("path", b"")
        if path in seen_paths:
            continue
        seen_paths.add(path)

        serial = info.get("serial_number", "")
        product = info.get("product_string", "FDD G1000")
        idx = len(found) + 1
        label = f"G1000 #{idx} [{product}] (HID)  VID=0x{G1000_VID:04X} PID=0x{G1000_PID:04X}"
        if serial:
            label += f"  S/N={serial}"

        found.append(FoundDevice(
            device_type=DeviceType.HID,
            label=label,
            hid_path=path,
            vid=G1000_VID,
            pid=G1000_PID,
            serial_number=serial,
        ))

    return found


def _scan_cdc() -> list[FoundDevice]:
    """Return CDC serial ports belonging to an RP2 device (VID=0x2E8A)."""
    try:
        from serial.tools import list_ports  # type: ignore
    except Exception:
        return []

    found: list[FoundDevice] = []
    system = platform.system()

    for port_info in list_ports.comports():
        vid = port_info.vid
        if vid != RP_VID:
            continue

        port = port_info.device
        description = port_info.description or "Unknown"
        serial = port_info.serial_number or ""

        # On macOS each USB serial device gets two entries: /dev/cu.* and /dev/tty.*
        # Keep only /dev/cu.* — it's what mpremote uses and doesn't block on DCD.
        if system == "Darwin" and not port.startswith("/dev/cu."):
            continue

        idx = len(found) + 1
        label = f"G1000 #{idx} [{description}] (MicroPython CDC)  {port}"
        if serial:
            label += f"  S/N={serial}"

        found.append(FoundDevice(
            device_type=DeviceType.CDC,
            label=label,
            port=port,
            vid=vid,
            pid=port_info.pid or 0,
            serial_number=serial,
        ))

    return found
