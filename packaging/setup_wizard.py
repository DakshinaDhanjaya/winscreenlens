"""Standalone GUI Setup Wizard for WinScreenLens_Setup.exe.

This script is packaged with the compressed WinScreenLens app payload into a single
downloadable WinScreenLens_Setup.exe. Running it extracts the app to the user's
Programs directory, creates Desktop & Start Menu shortcuts, registers an uninstaller
in Windows Add/Remove Programs, and launches WinScreenLens.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import winreg
import zipfile


APP_NAME = "WinScreenLens"
APP_VERSION = "2.0.0"
PUBLISHER = "WinScreenLens"


def _resource_path(filename: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


def _create_shortcut(
    target_exe: str,
    work_dir: str,
    shortcut_path: str,
    icon_path: str,
    description: str,
) -> None:
    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$s = $ws.CreateShortcut("{shortcut_path}"); '
        f'$s.TargetPath = "{target_exe}"; '
        f'$s.WorkingDirectory = "{work_dir}"; '
        f'$s.Description = "{description}"; '
    )
    if os.path.exists(icon_path):
        ps_script += f'$s.IconLocation = "{icon_path},0"; '
    ps_script += "$s.Save()"
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", ps_script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=True,
    )


def _register_uninstaller(install_dir: str, uninstall_cmd: str, icon_path: str, size_kb: int) -> None:
    reg_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, f"{APP_NAME} — Screen Translator")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_cmd)
        if os.path.exists(icon_path):
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, icon_path)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, max(1024, size_kb))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _set_autostart(exe_path: str, enable: bool) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class SetupWizardApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION} Setup")
        self.root.geometry("540x430")
        self.root.resizable(False, False)
        self.root.configure(bg="#0f172a")

        icon_path = _resource_path("app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        default_dir = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local"),
            "Programs",
            APP_NAME,
        )
        self.install_dir_var = tk.StringVar(value=default_dir)
        self.desktop_var = tk.BooleanVar(value=True)
        self.startmenu_var = tk.BooleanVar(value=True)
        self.autostart_var = tk.BooleanVar(value=False)
        self.launch_var = tk.BooleanVar(value=True)

        self._build_ui()

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#1e293b", height=76)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text=f"{APP_NAME} Installer",
            font=("Segoe UI", 16, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
        ).pack(anchor="w", padx=20, pady=(12, 2))
        tk.Label(
            header,
            text="Real-Time Screen, Subtitle & Slang Translator (Low Resource Edition)",
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#1e293b",
        ).pack(anchor="w", padx=20)

        body = tk.Frame(self.root, bg="#0f172a")
        body.pack(fill="both", expand=True, padx=22, pady=16)

        tk.Label(
            body,
            text="Install Location:",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#0f172a",
        ).pack(anchor="w")

        path_row = tk.Frame(body, bg="#0f172a")
        path_row.pack(fill="x", pady=(4, 14))
        self.path_entry = tk.Entry(
            path_row,
            textvariable=self.install_dir_var,
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief="flat",
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.browse_btn = tk.Button(
            path_row,
            text="Browse...",
            command=self._browse_folder,
            bg="#334155",
            fg="#f8fafc",
            activebackground="#475569",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=3,
        )
        self.browse_btn.pack(side="right")

        opts = [
            (self.desktop_var, "Create Desktop shortcut"),
            (self.startmenu_var, "Create Start Menu shortcut"),
            (self.autostart_var, "Start automatically with Windows"),
            (self.launch_var, "Launch WinScreenLens after installation"),
        ]
        for var, label in opts:
            cb = tk.Checkbutton(
                body,
                text=label,
                variable=var,
                font=("Segoe UI", 9),
                fg="#e2e8f0",
                bg="#0f172a",
                selectcolor="#1e293b",
                activebackground="#0f172a",
                activeforeground="#ffffff",
            )
            cb.pack(anchor="w", pady=2)

        self.status_var = tk.StringVar(value="Ready to install.")
        tk.Label(
            body,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f172a",
        ).pack(anchor="w", pady=(14, 4))

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Install.Horizontal.TProgressbar",
            troughcolor="#1e293b",
            background="#38bdf8",
            thickness=14,
        )
        self.progress = ttk.Progressbar(
            body,
            style="Install.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(fill="x", pady=(0, 14))

        footer = tk.Frame(self.root, bg="#0f172a")
        footer.pack(fill="x", padx=22, pady=(0, 16))

        self.cancel_btn = tk.Button(
            footer,
            text="Cancel",
            command=self.root.destroy,
            bg="#334155",
            fg="#f8fafc",
            relief="flat",
            padx=16,
            pady=6,
        )
        self.cancel_btn.pack(side="right")

        self.install_btn = tk.Button(
            footer,
            text="Install Now",
            command=self._start_install,
            bg="#0284c7",
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief="flat",
            padx=20,
            pady=6,
        )
        self.install_btn.pack(side="right", padx=(0, 10))

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.install_dir_var.get())
        if chosen:
            if not chosen.lower().endswith(APP_NAME.lower()):
                chosen = os.path.join(chosen, APP_NAME)
            self.install_dir_var.set(chosen)

    def _start_install(self) -> None:
        self.install_btn.config(state="disabled")
        self.browse_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")
        threading.Thread(target=self._run_install, daemon=True).start()

    def _update_ui(self, pct: int, msg: str) -> None:
        self.root.after(0, lambda: (self.progress.configure(value=pct), self.status_var.set(msg)))

    def _run_install(self) -> None:
        try:
            install_dir = self.install_dir_var.get().strip()
            if not install_dir:
                raise ValueError("Install path cannot be empty.")

            self._update_ui(5, "Stopping any existing WinScreenLens instance...")
            subprocess.run(
                ["taskkill", "/F", "/IM", f"{APP_NAME}.exe"],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            self._update_ui(10, "Preparing installation directory...")
            os.makedirs(install_dir, exist_ok=True)

            payload_zip = _resource_path("WinScreenLens_payload.zip")
            if not os.path.isfile(payload_zip):
                raise FileNotFoundError(f"Installer payload missing: {payload_zip}")

            total_bytes = 0
            with zipfile.ZipFile(payload_zip, "r") as zf:
                members = zf.infolist()
                total_count = max(1, len(members))
                for idx, member in enumerate(members):
                    zf.extract(member, install_dir)
                    total_bytes += member.file_size
                    if idx % 15 == 0 or idx == total_count - 1:
                        pct = 15 + int((idx + 1) / total_count * 70)
                        self._update_ui(pct, f"Extracting files ({idx + 1}/{total_count})...")

            exe_path = os.path.join(install_dir, f"{APP_NAME}.exe")
            icon_path = os.path.join(install_dir, "_internal", "app", "assets", "app_icon.ico")
            if not os.path.exists(icon_path):
                icon_path = exe_path

            self._update_ui(88, "Creating shortcuts...")
            user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
            desktop_lnk = os.path.join(user_profile, "Desktop", f"{APP_NAME}.lnk")
            start_lnk = os.path.join(
                os.environ.get("APPDATA") or os.path.join(user_profile, "AppData", "Roaming"),
                "Microsoft",
                "Windows",
                "Start Menu",
                "Programs",
                f"{APP_NAME}.lnk",
            )

            if self.desktop_var.get() and os.path.isdir(os.path.dirname(desktop_lnk)):
                _create_shortcut(exe_path, install_dir, desktop_lnk, icon_path, "WinScreenLens — Screen Translator")
            if self.startmenu_var.get() and os.path.isdir(os.path.dirname(start_lnk)):
                _create_shortcut(exe_path, install_dir, start_lnk, icon_path, "WinScreenLens — Screen Translator")

            self._update_ui(93, "Configuring uninstaller and startup...")
            _set_autostart(exe_path, self.autostart_var.get())

            uninst_bat = os.path.join(install_dir, "Uninstall.bat")
            with open(uninst_bat, "w", encoding="utf-8") as fh:
                fh.write("@echo off\n")
                fh.write(f'taskkill /F /IM "{APP_NAME}.exe" >nul 2>&1\n')
                fh.write(f'del /F /Q "{desktop_lnk}" >nul 2>&1\n')
                fh.write(f'del /F /Q "{start_lnk}" >nul 2>&1\n')
                fh.write(f'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "{APP_NAME}" /f >nul 2>&1\n')
                fh.write(f'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_NAME}" /f >nul 2>&1\n')
                fh.write('cd /d "%TEMP%"\n')
                fh.write(f'start /b "" cmd /c timeout /t 2 ^>nul ^& rmdir /S /Q "{install_dir}"\n')
                fh.write("echo WinScreenLens uninstalled.\n")

            _register_uninstaller(
                install_dir=install_dir,
                uninstall_cmd=f'cmd.exe /c "{uninst_bat}"',
                icon_path=icon_path,
                size_kb=max(1024, total_bytes // 1024),
            )

            self._update_ui(100, "Installation Complete!")

            if self.launch_var.get() and os.path.isfile(exe_path):
                subprocess.Popen([exe_path], cwd=install_dir)

            self.root.after(0, self._on_success)
        except Exception as exc:
            self.root.after(0, lambda err=str(exc): self._on_error(err))

    def _on_success(self) -> None:
        messagebox.showinfo(
            f"{APP_NAME} Setup",
            f"{APP_NAME} has been installed successfully!\n\n"
            "Look for the blue 'සි' icon in your System Tray (bottom-right).\n"
            "Hotkeys: Alt+W (Word Lookup), Ctrl+Shift+S (Snip), Ctrl+Shift+V (Subtitles), Esc (Clear).",
        )
        self.root.destroy()

    def _on_error(self, err: str) -> None:
        messagebox.showerror(f"{APP_NAME} Setup Error", f"Installation failed:\n\n{err}")
        self.install_btn.config(state="normal")
        self.browse_btn.config(state="normal")
        self.cancel_btn.config(state="normal")
        self.status_var.set("Installation failed.")


def main() -> None:
    root = tk.Tk()
    SetupWizardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
