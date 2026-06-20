"""FDD Firmware Updater — tkinter GUI application."""

from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

from .device_detector import DeviceType, FoundDevice, scan_devices
from .firmware_catalog import FirmwareEntry, FirmwareCatalog, load_catalog, check_for_updates
from .updater import UpdateError, flash_firmware
from .utils import is_admin, is_windows, relaunch_as_admin


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_TITLE = "FDD Firmware Updater"
WIN_WIDTH = 560
WIN_HEIGHT = 480
PAD = 10
LOG_HEIGHT = 12


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)
        self._center_window(WIN_WIDTH, WIN_HEIGHT)
        self._set_icon()

        # Data
        self._catalog: FirmwareCatalog = load_catalog()
        self._devices: list[FoundDevice] = []
        self._msg_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._update_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._scan_devices()
        self._poll_queue()
        self.after(1500, self._check_updates_startup)

    def _set_icon(self) -> None:
        """Set the window icon from the bundled PNG."""
        import platform
        from .utils import resource_path

        # On macOS the Dock/titlebar icon comes from the .icns in the .app bundle
        # (set via the PyInstaller spec).  We still set a PhotoImage so the
        # tkinter window gets an icon when running from source.
        try:
            icon_path = resource_path("icons/FDD_logo.png")
            if icon_path.exists():
                img = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, img)
                self._icon_ref = img  # prevent garbage collection
        except Exception:
            pass  # non-fatal — app works fine without the icon

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)

        # ── Device row ────────────────────────────────────────────────
        device_frame = ttk.LabelFrame(self, text="Device", padding=PAD)
        device_frame.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
        device_frame.columnconfigure(1, weight=1)

        ttk.Label(device_frame, text="Connected device:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self._device_var = tk.StringVar()
        self._device_combo = ttk.Combobox(
            device_frame,
            textvariable=self._device_var,
            state="readonly",
            width=40,
        )
        self._device_combo.grid(row=0, column=1, sticky="ew")

        self._scan_btn = ttk.Button(device_frame, text="Scan", command=self._scan_devices, width=8)
        self._scan_btn.grid(row=0, column=2, padx=(8, 0))

        # ── Firmware row ──────────────────────────────────────────────
        fw_frame = ttk.LabelFrame(self, text="Firmware", padding=PAD)
        fw_frame.grid(row=1, column=0, sticky="ew", padx=PAD, pady=4)
        fw_frame.columnconfigure(1, weight=1)

        ttk.Label(fw_frame, text="Target firmware:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self._fw_var = tk.StringVar()
        self._fw_combo = ttk.Combobox(
            fw_frame,
            textvariable=self._fw_var,
            state="readonly",
            width=40,
        )
        fw_names = [str(e) for e in self._catalog.entries]
        self._fw_combo["values"] = fw_names
        if fw_names:
            self._fw_combo.current(0)
        self._fw_combo.grid(row=0, column=1, sticky="ew")

        # ── Progress bar ──────────────────────────────────────────────
        prog_frame = ttk.Frame(self)
        prog_frame.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(4, 0))
        prog_frame.columnconfigure(0, weight=1)

        self._progress = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self._progress.grid(row=0, column=0, sticky="ew")

        self._status_var = tk.StringVar(value="Ready.")
        ttk.Label(prog_frame, textvariable=self._status_var, anchor="w").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )

        # ── Log area ──────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self, text="Log", padding=PAD)
        log_frame.grid(row=3, column=0, sticky="nsew", padx=PAD, pady=4)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._log_text = scrolledtext.ScrolledText(
            log_frame,
            height=LOG_HEIGHT,
            state="disabled",
            wrap="word",
            font=("Courier", 10) if tk.TkVersion >= 8.5 else ("Courier", 10),
        )
        self._log_text.grid(row=0, column=0, sticky="nsew")

        clear_btn = ttk.Button(log_frame, text="Clear", command=self._clear_log, width=6)
        clear_btn.grid(row=1, column=0, sticky="e", pady=(4, 0))

        # ── Action buttons ────────────────────────────────────────────
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, sticky="ew", padx=PAD, pady=(4, PAD))

        self._update_btn = ttk.Button(
            btn_frame, text="Update Firmware", command=self._start_update, width=20
        )
        self._update_btn.pack(side="left", padx=(0, 8))

        self._check_btn = ttk.Button(
            btn_frame, text="Check for Updates", command=self._check_updates, width=18
        )
        self._check_btn.pack(side="left")

    # ------------------------------------------------------------------
    # Device scanning
    # ------------------------------------------------------------------

    def _scan_devices(self) -> None:
        self._set_controls_enabled(False)
        self._log("Scanning for devices...")
        self._status("Scanning...")

        def _do_scan() -> None:
            try:
                devices = scan_devices()
                self._msg_queue.put(("scan_done", devices))
            except Exception as exc:
                self._msg_queue.put(("scan_error", str(exc)))

        threading.Thread(target=_do_scan, daemon=True).start()

    def _on_scan_done(self, devices: list[FoundDevice]) -> None:
        self._devices = devices
        labels = [d.label for d in devices]
        self._device_combo["values"] = labels
        if labels:
            self._device_combo.current(0)
            self._log(f"Found {len(devices)} device(s).")
            for d in devices:
                type_str = d.device_type.name
                self._log(f"  [{type_str}] {d.label}")
        else:
            self._device_var.set("")
            self._log("No G1000 devices found. Check USB connection and try Scan.")
        self._status("Ready.")
        self._set_controls_enabled(True)

    # ------------------------------------------------------------------
    # Firmware update
    # ------------------------------------------------------------------

    def _start_update(self) -> None:
        device = self._selected_device()
        firmware = self._selected_firmware()

        if device is None:
            messagebox.showwarning(APP_TITLE, "No device selected. Please scan first.")
            return
        if firmware is None:
            messagebox.showwarning(APP_TITLE, "No firmware selected.")
            return

        confirm = messagebox.askyesno(
            APP_TITLE,
            f"Flash device:\n  {device.label}\n\nWith firmware:\n  {firmware.name} v{firmware.version}\n\nProceed?",
        )
        if not confirm:
            return

        self._set_controls_enabled(False)
        self._progress["value"] = 0
        self._status(f"Updating to {firmware.name} v{firmware.version} ...")
        self._log(f"--- Update started: {firmware.name} v{firmware.version} ---")

        def _do_update() -> None:
            try:
                flash_firmware(
                    device=device,
                    firmware=firmware,
                    log=lambda msg: self._msg_queue.put(("log", msg)),
                    progress=lambda pct: self._msg_queue.put(("progress", pct)),
                )
                self._msg_queue.put(("update_done", None))
            except UpdateError as exc:
                self._msg_queue.put(("update_error", str(exc)))
            except Exception as exc:
                self._msg_queue.put(("update_error", f"Unexpected error: {exc}"))

        self._update_thread = threading.Thread(target=_do_update, daemon=True)
        self._update_thread.start()

    def _on_update_done(self) -> None:
        self._progress["value"] = 100
        self._status("Update complete!")
        self._log("--- Update finished successfully ---")
        self._set_controls_enabled(True)
        self._scan_devices()
        messagebox.showinfo(APP_TITLE, "Firmware updated successfully!")

    def _on_update_error(self, msg: str) -> None:
        self._status("Update failed.")
        self._log(f"ERROR: {msg}")
        self._set_controls_enabled(True)
        messagebox.showerror(APP_TITLE, f"Update failed:\n\n{msg}")

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _check_updates_startup(self) -> None:
        """Silent background check on launch — only prompts if update found."""
        def _do_check() -> None:
            available, version, url = check_for_updates(self._catalog)
            if available:
                self._msg_queue.put(("check_done", (available, version, url, True)))

        threading.Thread(target=_do_check, daemon=True).start()

    def _check_updates(self) -> None:
        self._set_controls_enabled(False)
        self._log("Checking for application updates...")

        def _do_check() -> None:
            available, version, url = check_for_updates(
                self._catalog,
                log=lambda msg: self._msg_queue.put(("log", msg)),
            )
            self._msg_queue.put(("check_done", (available, version, url, False)))

        threading.Thread(target=_do_check, daemon=True).start()

    def _on_check_done(self, result: tuple[bool, str, str, bool]) -> None:
        available, version, asset_url, from_startup = result
        self._set_controls_enabled(True)
        if not available:
            if not from_startup:
                messagebox.showinfo(APP_TITLE, "You are running the latest version.")
            return

        if asset_url:
            answer = messagebox.askyesno(
                APP_TITLE,
                f"A new version is available: v{version}\n\nDownload and install now?",
            )
            if answer:
                self._download_and_install(asset_url, version)
        else:
            # No installable asset for this platform — open browser as fallback
            import webbrowser
            answer = messagebox.askyesno(
                APP_TITLE,
                f"A new version is available: v{version}\n\nOpen the download page?",
            )
            if answer:
                webbrowser.open(
                    "https://github.com/FlightDeckDIY/fdd-firmware-updater/releases/latest"
                )

    # ------------------------------------------------------------------
    # Auto-update download + install
    # ------------------------------------------------------------------

    def _download_and_install(self, url: str, version: str) -> None:
        self._set_controls_enabled(False)
        self._log(f"Downloading v{version}...")

        suffix = Path(url).suffix  # .dmg or .exe
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(tmp_fd)

        def _do_download() -> None:
            try:
                import requests  # type: ignore
                with requests.get(url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length", 0))
                    downloaded = 0
                    with open(tmp_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = int(downloaded * 100 / total)
                                self._msg_queue.put(("progress", pct))
                self._msg_queue.put(("install_ready", tmp_path))
            except Exception as exc:
                self._msg_queue.put(("install_error", str(exc)))

        threading.Thread(target=_do_download, daemon=True).start()

    def _on_install_ready(self, tmp_path: str) -> None:
        self._log("Download complete. Installing...")
        self._progress["value"] = 100
        system = platform.system()
        try:
            if system == "Darwin":
                self._apply_update_macos(tmp_path)
            elif system == "Windows":
                self._apply_update_windows(tmp_path)
            else:
                messagebox.showerror(APP_TITLE, f"Auto-install not supported on {system}.")
                self._set_controls_enabled(True)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Install failed:\n\n{exc}")
            self._set_controls_enabled(True)

    def _apply_update_macos(self, dmg_path: str) -> None:
        """Mount DMG, write a shell script to replace the .app after we quit, relaunch."""
        # Find the running .app bundle (3 levels up from the MacOS binary)
        if getattr(sys, "frozen", False):
            current_app = Path(sys.executable).parents[2]
        else:
            current_app = None

        if current_app is None or current_app.suffix != ".app":
            # Running from source — just mount and let the user drag manually
            subprocess.Popen(["hdiutil", "attach", dmg_path])
            messagebox.showinfo(APP_TITLE, "DMG mounted. Drag the new app to Applications.")
            return

        install_dir = current_app.parent  # e.g. /Applications
        app_name = current_app.name       # e.g. FDD Firmware Updater.app
        pid = os.getpid()

        script = f"""#!/bin/bash
# Wait for the running app to exit
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done

# Mount the DMG
MOUNT=$(hdiutil attach -nobrowse -readonly "{dmg_path}" | tail -1 | awk '{{print $NF}}')

# Replace the old .app
rm -rf "{install_dir}/{app_name}"
cp -R "$MOUNT/{app_name}" "{install_dir}/{app_name}"

# Clean up
hdiutil detach "$MOUNT" -quiet
rm -f "{dmg_path}"

# Relaunch
open "{install_dir}/{app_name}"
"""
        script_fd, script_path = tempfile.mkstemp(suffix=".sh")
        with os.fdopen(script_fd, "w") as f:
            f.write(script)
        os.chmod(script_path, 0o755)
        subprocess.Popen(["bash", script_path])
        self._log("Update ready. Relaunching...")
        self.after(300, self.quit)

    def _apply_update_windows(self, exe_path: str) -> None:
        """Write a batch script to replace the running exe after quit, relaunch."""
        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable)
        else:
            messagebox.showinfo(APP_TITLE, "Installer downloaded. Run it to update.")
            subprocess.Popen([exe_path], shell=True)
            return

        pid = os.getpid()
        new_exe = exe_path
        target = str(current_exe)

        batch = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
move /Y "{new_exe}" "{target}"
start "" "{target}"
del "%~f0"
"""
        bat_fd, bat_path = tempfile.mkstemp(suffix=".bat")
        with os.fdopen(bat_fd, "w") as f:
            f.write(batch)
        subprocess.Popen([bat_path], shell=True, close_fds=True)
        self._log("Update ready. Relaunching...")
        self.after(300, self.quit)

    # ------------------------------------------------------------------
    # Message queue polling (GUI update from background threads)
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "log":
                    self._log(str(payload))
                elif kind == "progress":
                    self._progress["value"] = int(payload)
                elif kind == "status":
                    self._status(str(payload))
                elif kind == "scan_done":
                    self._on_scan_done(payload)  # type: ignore[arg-type]
                elif kind == "scan_error":
                    self._log(f"Scan error: {payload}")
                    self._status("Scan failed.")
                    self._set_controls_enabled(True)
                elif kind == "update_done":
                    self._on_update_done()
                elif kind == "update_error":
                    self._on_update_error(str(payload))
                elif kind == "check_done":
                    self._on_check_done(payload)  # type: ignore[arg-type]
                elif kind == "install_ready":
                    self._on_install_ready(str(payload))
                elif kind == "install_error":
                    self._log(f"Download failed: {payload}")
                    self._status("Download failed.")
                    self._set_controls_enabled(True)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", message + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _status(self, msg: str) -> None:
        self._status_var.set(msg)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self._scan_btn, self._update_btn, self._check_btn,
                       self._device_combo, self._fw_combo):
            widget.configure(state=state if widget is not self._device_combo
                             and widget is not self._fw_combo else "readonly" if enabled else "disabled")

    def _selected_device(self) -> FoundDevice | None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._devices):
            return None
        return self._devices[idx]

    def _selected_firmware(self) -> FirmwareEntry | None:
        idx = self._fw_combo.current()
        if idx < 0 or idx >= len(self._catalog.entries):
            return None
        return self._catalog.entries[idx]

    def _center_window(self, width: int, height: int) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if is_windows() and not is_admin():
        relaunch_as_admin()
        sys.exit(0)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
