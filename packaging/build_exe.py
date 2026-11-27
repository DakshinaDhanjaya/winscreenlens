"""PyInstaller packaging script for creating a lean, low-resource standalone WinScreenLens.exe."""

from __future__ import annotations

import os
import subprocess
import sys


EXCLUDED_MODULES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtSvg",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
    "google.genai",
    "cryptography",
    "pydantic",
    "pydantic_core",
    "httpx2",
    "websockets",
    "tkinter",
    "matplotlib",
    "scipy",
    "IPython",
]


def build_executable() -> None:
    """Build lean standalone Windows executable for WinScreenLens."""
    print("=" * 60)
    print(" WinScreenLens — Lean Standalone Executable Builder")
    print("=" * 60)

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root_dir)

    run_script = os.path.join(root_dir, "run.py")
    if not os.path.exists(run_script):
        print(f"[Error] Entry point '{run_script}' not found!")
        sys.exit(1)

    build_dir = os.path.join(root_dir, "build")
    os.makedirs(build_dir, exist_ok=True)

    icon_file = os.path.join(root_dir, "app", "assets", "app_icon.ico")
    icon_arg = [f"--icon={icon_file}"] if os.path.exists(icon_file) else []

    exclude_args = []
    for mod in EXCLUDED_MODULES:
        exclude_args.extend(["--exclude-module", mod])

    assets_dir = os.path.join(root_dir, "app", "assets")

    # PyInstaller's built-in PySide6 hooks automatically collect only QtCore/QtGui/QtWidgets + QPA.
    cmd = (
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconsole",
            "--name=WinScreenLens",
            "--clean",
            "--onedir",
            "--noconfirm",
            f"--specpath={build_dir}",
        ]
        + icon_arg
        + exclude_args
        + [
            f"--add-data={assets_dir};app/assets",
            "--hidden-import=PySide6.QtCore",
            "--hidden-import=PySide6.QtGui",
            "--hidden-import=PySide6.QtWidgets",
            "--hidden-import=pynput",
            "--hidden-import=pynput.keyboard",
            "--hidden-import=pynput.keyboard._win32",
            "--hidden-import=pynput.mouse._win32",
            "--hidden-import=rapidocr",
            "--hidden-import=onnxruntime",
            "--collect-all=rapidocr",
            run_script,
        ]
    )

    print("Running build command...\n")
    try:
        subprocess.run(cmd, check=True)
        print("\n" + "=" * 60)
        print(" Lean Build Complete!")
        print(f" Output folder: {os.path.join(root_dir, 'dist', 'WinScreenLens')}")
        print(" Executable:    dist\\WinScreenLens\\WinScreenLens.exe")
        print("=" * 60)
    except subprocess.CalledProcessError as err:
        print(f"\n[Build Error] PyInstaller failed with exit code: {err.returncode}")
        sys.exit(err.returncode)
    except FileNotFoundError:
        print("\n[Error] PyInstaller is not installed in the current environment.")
        print("Please run: pip install pyinstaller")
        sys.exit(1)


if __name__ == "__main__":
    build_executable()
