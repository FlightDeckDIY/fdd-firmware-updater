# FDD Firmware Updater

A cross-platform GUI application for updating firmware on FDD G1000 devices (Raspberry Pi RP2350B). Supports switching between two firmware variants:

| Firmware | Communication | Use case |
|---|---|---|
| **G1000 HID (C/C++ SDK)** | USB HID | Production — no serial driver needed |
| **MicroPython CDC** | USB Serial (CDC) | Development — REPL and file access via mpremote |

The app is self-contained — no Python installation or external tools are required on end-user machines.

---

## For Users

### Connecting a Device

Connect the G1000 device via USB. The app detects three possible device states automatically:

- **HID** — device is running the C/C++ HID firmware
- **MicroPython CDC** — device is running MicroPython
- **BOOTSEL** — device is in bootloader/mass-storage mode (e.g. held BOOTSEL button on power-up)

### Flashing Firmware

1. Open **FDD Firmware Updater**
2. Click **Scan** — your device should appear in the Connected device dropdown
3. Select the target firmware from the **Target firmware** dropdown
4. Click **Update Firmware** and confirm the prompt
5. Watch the log — the app will enter BOOTSEL mode automatically, flash the UF2, and (for MicroPython) upload the application files
6. Done — the device reboots into the new firmware

> **Windows only:** The app automatically stops the `FlightDeckConnect` and `FlightDeckConnectHID` services before flashing and restarts them when complete. No manual service management is needed.

### Check for Updates

Click **Check for Updates** to query GitHub Releases for a newer version of the updater itself. This requires an internet connection.

---

## For Developers / Maintainers

### Prerequisites

- Python 3.11 or newer (`python3.14` recommended)
- macOS (Apple Silicon) or Windows x64
- On macOS: `brew install hidapi` for HID device access

### Running from Source

```bash
# Clone and install
git clone <repo-url>
cd fdd-firmware-updater
pip install -e .

# Run the GUI
python3 -m fdd_updater.app
# or
fdd-updater
```

### Project Layout

```
fdd-firmware-updater/
├── fdd_updater/
│   ├── app.py               # tkinter GUI
│   ├── device_detector.py   # USB HID + CDC + BOOTSEL discovery
│   ├── firmware_catalog.py  # manifest.json loading + GitHub update check
│   ├── updater.py           # flash logic: bootsel → UF2 copy → file upload
│   ├── service_manager.py   # Windows service stop/start
│   └── utils.py             # BOOTSEL volume detection, resource path helper
├── resources/
│   ├── firmware/
│   │   ├── manifest.json              # Firmware catalog — edit this to add/update firmware
│   │   ├── hid/
│   │   │   └── G1000_HID.uf2         # HID firmware binary
│   │   └── micropython/
│   │       ├── fdd_g1000_1229251426.uf2   # MicroPython runtime UF2
│   │       ├── main.py
│   │       └── *.py                       # MicroPython application files
│   └── tools/
│       ├── macos/picotool             # picotool binary (auto-populated by build script)
│       └── windows/picotool.exe      # picotool binary (add manually from pico-sdk releases)
├── installer/
│   ├── fdd_updater.spec       # PyInstaller spec
│   ├── build_macos.sh         # macOS build script → .app + .dmg
│   └── build_windows.ps1      # Windows build script → .exe directory
├── launcher.py                # PyInstaller entry point (do not rename)
└── pyproject.toml
```

---

## Updating Firmware

All firmware metadata lives in **`resources/firmware/manifest.json`**. This is the only file you need to edit when releasing new firmware.

### manifest.json Schema

```json
{
  "manifest_version": 1,
  "github_releases_url": "https://api.github.com/repos/<org>/<repo>/releases/latest",
  "firmware": [
    {
      "id": "hid",
      "name": "G1000 HID (C/C++ SDK)",
      "version": "0.2.0",
      "type": "hid",
      "uf2": "hid/G1000_HID.uf2",
      "app_files": [],
      "description": "Human-readable description shown in the UI."
    },
    {
      "id": "micropython",
      "name": "MicroPython CDC",
      "version": "0.1.2",
      "type": "cdc",
      "uf2": "micropython/fdd_g1000_1229251426.uf2",
      "app_files": [
        "micropython/main.py",
        "micropython/config.py"
      ],
      "description": "MicroPython firmware."
    }
  ]
}
```

| Field | Description |
|---|---|
| `id` | Internal identifier — must be unique, used in code logic |
| `name` | Display name shown in the firmware dropdown |
| `version` | Semantic version string — displayed in the UI |
| `type` | `"hid"` or `"cdc"` — controls the update flow |
| `uf2` | Path to the UF2 file, relative to `resources/firmware/` |
| `app_files` | (`cdc` only) List of `.py` files to upload after flashing, relative to `resources/firmware/` |
| `description` | Human-readable description (informational only) |
| `github_releases_url` | GitHub API URL used by **Check for Updates** |

### Adding a New HID Firmware Version

1. Copy the new `.uf2` into `resources/firmware/hid/`
2. Update `manifest.json` — change `"uf2"` to the new filename and bump `"version"`
3. Rebuild (see below)

### Adding a New MicroPython Version

1. Copy the new MicroPython runtime `.uf2` into `resources/firmware/micropython/`  
   (rename it if needed — the filename is arbitrary)
2. Copy updated `.py` application files into `resources/firmware/micropython/`
3. Update `manifest.json` — update `"uf2"`, `"version"`, and `"app_files"` as needed
4. Rebuild

### Adding an Entirely New Firmware Type

Add a new entry to the `"firmware"` array in `manifest.json`. Set `"type"` to `"hid"` (UF2 only) or `"cdc"` (UF2 + file upload). No code changes are needed for new entries of existing types.

---

## Building a Distributable

### macOS (Apple Silicon)

```bash
./installer/build_macos.sh
```

This will:
1. Detect and use Python 3.11+ from your PATH
2. Install dependencies (PyInstaller, project deps)
3. Copy `picotool` from Homebrew into `resources/tools/macos/` (install first with `brew install picotool`)
4. Run PyInstaller → `dist/FDD Firmware Updater.app`
5. Create `dist/FDD-Firmware-Updater-macOS.dmg`

### Windows x64

From a PowerShell terminal:

```powershell
.\installer\build_windows.ps1
```

Before building, place `picotool.exe` from the [pico-sdk GitHub releases](https://github.com/raspberrypi/picotool/releases) at `resources/tools/windows/picotool.exe`.

Output: `dist\FDD Firmware Updater\` — zip this folder or wrap with Inno Setup for distribution.

### PyInstaller Notes

- Entry point is `launcher.py` — do not use `fdd_updater/app.py` directly (relative imports break in frozen bundles)
- `mpremote` is called via its Python API (`mpremote.main.main()`) not as a subprocess — this is intentional, since `sys.executable` inside a frozen app is the bootloader binary, not a Python interpreter
- The `resources/` tree is embedded in the bundle via `--add-data` in the spec file
- `collect_all("mpremote")` in the spec ensures all mpremote modules are bundled even though they are never statically imported

---

## How the Update Flow Works

### HID Firmware → Any Target

1. Sends a `DEVICE_CTL: ENTER_BOOT` HID report (report ID `0x12`, payload `0x02`) to VID `0x2E8A` / PID `0x10F7`
2. Device calls `reset_usb_boot()` and re-enumerates as USB mass-storage (`/Volumes/RP2350` on macOS)
3. UF2 is copied to the mounted volume — device flashes and reboots automatically
4. If target is MicroPython: waits for CDC device to re-enumerate, then uploads `.py` files via mpremote

### MicroPython CDC → Any Target

1. Calls `mpremote connect <port> bootloader` — triggers `machine.bootloader()` on the device
2. Device enters BOOTSEL mass-storage mode
3. Same UF2 copy + optional file upload as above

### Windows Service Management

On Windows, `FlightDeckConnect` and `FlightDeckConnectHID` services hold the COM port open. The app calls `sc stop` on both before any operation and `sc start` after, even if the update fails.

---

## Device Detection

The app scans for devices in this order on each **Scan**:

1. **BOOTSEL volume** — looks for a mounted volume named `RPI-RP2` or `RP2350` containing `INFO_UF2.TXT`
2. **HID device** — enumerates USB HID devices matching VID `0x2E8A` / PID `0x10F7`
3. **CDC serial port** — scans serial ports for VID `0x2E8A`; on macOS keeps only `/dev/cu.*` entries (what mpremote uses)

If a device is in BOOTSEL mode when you open the app, you can flash directly without needing to enter bootloader first.
