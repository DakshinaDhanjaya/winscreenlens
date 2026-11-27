"""WinScreenLens Automated Installer and Shortcut Setup Helper."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def create_shortcut(
    target_exe: str,
    arguments: str,
    work_dir: str,
    shortcut_path: str,
    icon_path: str,
    description: str,
) -> bool:
    """Create a Windows .lnk shortcut using PowerShell COM object."""
    ps_cmd = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target_exe}'; "
        f"$s.Arguments = '{arguments}'; "
        f"$s.WorkingDirectory = '{work_dir}'; "
        f"$s.Description = '{description}'; "
        f"$s.WindowStyle = 7; "
    )
    if os.path.exists(icon_path):
        ps_cmd += f"$s.IconLocation = '{icon_path},0'; "
    ps_cmd += "$s.Save()"

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except Exception as exc:
        print(f"[Warning] Failed to create shortcut at {shortcut_path}: {exc}")
        return False


def run_installer() -> None:
    source_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print("=" * 60)
    print("       WinScreenLens - Windows Setup and Installer")
    print("=" * 60)

    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    default_target = os.path.join(local_app_data, "Programs", "WinScreenLens")

    target_dir = default_target
    copy_files = True

    try:
        os.makedirs(target_dir, exist_ok=True)
    except (PermissionError, OSError) as perm_err:
        print(f"[Notice] Could not write to {default_target} ({perm_err}).")
        print(f"         Switching to Portable Setup in current folder: {source_dir}")
        target_dir = source_dir
        copy_files = False

    if copy_files and os.path.abspath(target_dir) != os.path.abspath(source_dir):
        print(f"\n[1/4] Installing application files to:\n      {target_dir}")
        exclude_dirs = {".git", ".github", "build", "dist", "__pycache__", ".vscode", "packaging", "tests"}
        for item in os.listdir(source_dir):
            if item in exclude_dirs:
                continue
            src_item = os.path.join(source_dir, item)
            dst_item = os.path.join(target_dir, item)
            try:
                if os.path.isdir(src_item):
                    if os.path.exists(dst_item):
                        shutil.rmtree(dst_item, ignore_errors=True)
                    shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_item, dst_item)
            except Exception as exc:
                print(f"      [Notice] Skipping {item}: {exc}")
    else:
        print(f"\n[1/4] Configuring application in current folder:\n      {target_dir}")

    pythonw_exe = os.path.join(target_dir, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = os.path.join(source_dir, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = sys.executable.replace("python.exe", "pythonw.exe")

    run_py = os.path.join(target_dir, "run.py")
    icon_ico = os.path.join(target_dir, "app", "assets", "app_icon.ico")
    if not os.path.exists(icon_ico):
        icon_ico = os.path.join(source_dir, "app", "assets", "app_icon.ico")

    print("\n[2/4] Setting up Desktop and Start Menu shortcuts...")
    user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    desktop_dir = os.path.join(user_profile, "Desktop")
    if os.path.exists(desktop_dir):
        desk_lnk = os.path.join(desktop_dir, "WinScreenLens.lnk")
        if create_shortcut(pythonw_exe, f'"{run_py}"', target_dir, desk_lnk, icon_ico, "WinScreenLens - Screen Translator"):
            print(f"      * Desktop shortcut created: {desk_lnk}")

    app_data = os.environ.get("APPDATA") or os.path.join(user_profile, "AppData", "Roaming")
    start_menu_dir = os.path.join(app_data, "Microsoft", "Windows", "Start Menu", "Programs")
    if os.path.exists(start_menu_dir):
        start_lnk = os.path.join(start_menu_dir, "WinScreenLens.lnk")
        if create_shortcut(pythonw_exe, f'"{run_py}"', target_dir, start_lnk, icon_ico, "WinScreenLens - Screen Translator"):
            print(f"      * Start Menu shortcut created: {start_lnk}")

    print("\n[3/4] Creating Uninstaller...")
    uninstaller_bat = os.path.join(target_dir, "Uninstall_WinScreenLens.bat")
    try:
        with open(uninstaller_bat, "w", encoding="utf-8") as f:
            f.write("@echo off\n")
            f.write("echo Uninstalling WinScreenLens...\n")
            f.write('taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq WinScreenLens*" >nul 2>&1\n')
            f.write(f'del /F /Q "{os.path.join(desktop_dir, "WinScreenLens.lnk")}" >nul 2>&1\n')
            f.write(f'del /F /Q "{os.path.join(start_menu_dir, "WinScreenLens.lnk")}" >nul 2>&1\n')
            f.write("echo WinScreenLens shortcuts removed.\n")
            f.write(f"echo To remove files, you may delete: {target_dir}\n")
            f.write("echo WinScreenLens uninstalled successfully.\n")
            f.write("pause\n")
        print(f"      * Uninstaller created at: {uninstaller_bat}")
    except Exception as exc:
        print(f"      [Notice] Could not create uninstaller script: {exc}")

    print("\n[4/4] Setup Complete!")
    print("=" * 60)
    print(" WinScreenLens has been successfully installed!")
    print("  - Launch anytime from Desktop or Start Menu")
    print("  - Alt + W  : Instant word / sentence lookup")
    print("  - Alt + Q / Ctrl+Shift+V : Video subtitle mode")
    print("  - Esc      : Dismiss / close overlays")
    print("=" * 60)

    try:
        subprocess.Popen([pythonw_exe, run_py], cwd=target_dir)
        print("\n WinScreenLens has been launched into your Windows System Tray!")
    except Exception as exc:
        print(f"\n[Notice] Could not auto-launch: {exc}")


if __name__ == "__main__":
    run_installer()
