@echo off
title WinScreenLens 1-Click Installer
cd /d "%~dp0"
echo ============================================================
echo         WinScreenLens - 1-Click Windows Setup
echo ============================================================
echo.
if exist ".\.venv\Scripts\python.exe" (
    ".\.venv\Scripts\python.exe" "%~dp0installer.py"
) else if exist "C:\Python314\python.exe" (
    "C:\Python314\python.exe" "%~dp0installer.py"
) else (
    python "%~dp0installer.py"
)
echo.
pause
