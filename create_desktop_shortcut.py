"""Create a 1-click Desktop Shortcut for WinScreenLens that runs with pythonw (no console)."""

from __future__ import annotations

import os
import sys


def create_desktop_shortcut() -> None:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    pythonw_exe = os.path.join(root_dir, ".venv", "Scripts", "pythonw.exe")
    run_py = os.path.join(root_dir, "run.py")

    # Get user desktop directory
    desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.exists(desktop_dir):
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

    shortcut_path = os.path.join(desktop_dir, "WinScreenLens.lnk")

    # Create shortcut using Windows WScript.Shell
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(shortcut_path)
        shortcut.TargetPath = pythonw_exe
        shortcut.Arguments = f'"{run_py}"'
        shortcut.WorkingDirectory = root_dir
        shortcut.Description = "WinScreenLens — Screen Translator & Pronunciation Engine"
        shortcut.WindowStyle = 7  # Minimized / Silent
        shortcut.Save()
        print(f"Created Desktop Shortcut: {shortcut_path}")
    except Exception as exc:
        print(f"Could not create .lnk shortcut via COM: {exc}")


if __name__ == "__main__":
    create_desktop_shortcut()
