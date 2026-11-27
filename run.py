"""Entry point for WinScreenLens."""

from __future__ import annotations

import os
import sys

# Auto-bootstrap into project virtual environment if dependencies are missing in current environment
if not getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
    VENV_PYTHON = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")

    if os.path.isfile(VENV_PYTHON):
        current_exe = os.path.abspath(sys.executable).lower()
        target_exe = os.path.abspath(VENV_PYTHON).lower()
        if current_exe != target_exe:
            try:
                import PIL  # noqa: F401
                import PySide6  # noqa: F401
            except ImportError:
                import subprocess

                try:
                    sys.exit(subprocess.call([VENV_PYTHON] + sys.argv))
                except Exception as exc:
                    sys.stderr.write(f"Failed to launch via virtual environment: {exc}\n")
                    sys.exit(1)

from app.main_app import main

if __name__ == "__main__":
    main()

