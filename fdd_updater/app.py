"""FDD Firmware Updater — tkinter GUI application."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

from .device_detector import DeviceType, FoundDevice, scan_devices
from .firmware_catalog import FirmwareEntry, FirmwareCatalog, load_catalog, check_for_updates
from .updater import UpdateError, flash_firmware


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

        # Data
        self._catalog: FirmwareCatalog = load_catalog()
        self._devices: list[FoundDevice] = []
        self._msg_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._update_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._scan_devices()
        self._poll_queue()

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

    def _check_updates(self) -> None:
        self._set_controls_enabled(False)
        self._log("Checking for application updates...")

        def _do_check() -> None:
            available, version = check_for_updates(
                self._catalog,
                log=lambda msg: self._msg_queue.put(("log", msg)),
            )
            self._msg_queue.put(("check_done", (available, version)))

        threading.Thread(target=_do_check, daemon=True).start()

    def _on_check_done(self, result: tuple[bool, str]) -> None:
        available, version = result
        self._set_controls_enabled(True)
        if available:
            messagebox.showinfo(
                APP_TITLE,
                f"A new version is available: v{version}\n\nVisit the releases page to download.",
            )
        else:
            messagebox.showinfo(APP_TITLE, "You are running the latest version.")

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
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
