@echo off
cd /d "%~dp0"
if exist ".\.venv\Scripts\pythonw.exe" (
    start "" ".\.venv\Scripts\pythonw.exe" "run.py"
) else (
    start "" "C:\Python314\pythonw.exe" "run.py"
)
exit
