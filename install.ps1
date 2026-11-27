# WinScreenLens Automated Installer
param(
    [switch]$InstallLocal = $false
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       WinScreenLens - Windows Installer and Setup          " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $sourceDir) { $sourceDir = (Get-Location).Path }

if ($InstallLocal) {
    $targetDir = $sourceDir
    Write-Host "[Mode] Running in portable mode: $targetDir" -ForegroundColor Yellow
} else {
    $localAppData = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::LocalApplicationData)
    $targetDir = [System.IO.Path]::Combine($localAppData, "Programs", "WinScreenLens")
    Write-Host "[1/4] Installing files to: $targetDir" -ForegroundColor Green
    
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $excludeList = @(".git", "build", "dist", "__pycache__", ".vscode")
    Get-ChildItem -Path $sourceDir | Where-Object { $_.Name -notin $excludeList } | ForEach-Object {
        $destPath = Join-Path $targetDir $_.Name
        if ($_.PSIsContainer) {
            Copy-Item -Path $_.FullName -Destination $destPath -Recurse -Force
        } else {
            Copy-Item -Path $_.FullName -Destination $destPath -Force
        }
    }
}

$pythonw = [System.IO.Path]::Combine($targetDir, ".venv\Scripts\pythonw.exe")
if (-not (Test-Path $pythonw)) {
    $pythonw = [System.IO.Path]::Combine($sourceDir, ".venv\Scripts\pythonw.exe")
}
if (-not (Test-Path $pythonw)) {
    $pythonw = "pythonw.exe"
}

$runPy = [System.IO.Path]::Combine($targetDir, "run.py")
$iconPath = [System.IO.Path]::Combine($targetDir, "app\assets\app_icon.ico")
if (-not (Test-Path $iconPath)) {
    $iconPath = [System.IO.Path]::Combine($sourceDir, "app\assets\app_icon.ico")
}

Write-Host "[2/4] Creating Desktop and Start Menu Shortcuts..." -ForegroundColor Green
$WshShell = New-Object -ComObject WScript.Shell

$desktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
if ($desktopPath -and (Test-Path $desktopPath)) {
    $desktopShortcutPath = Join-Path $desktopPath "WinScreenLens.lnk"
    $desktopShortcut = $WshShell.CreateShortcut($desktopShortcutPath)
    $desktopShortcut.TargetPath = $pythonw
    $desktopShortcut.Arguments = "`"$runPy`""
    $desktopShortcut.WorkingDirectory = $targetDir
    $desktopShortcut.Description = "WinScreenLens - Screen Translator and Pronunciation Engine"
    if (Test-Path $iconPath) {
        $desktopShortcut.IconLocation = "$iconPath,0"
    }
    $desktopShortcut.WindowStyle = 7
    $desktopShortcut.Save()
    Write-Host "  -> Created Desktop Shortcut: $desktopShortcutPath" -ForegroundColor Gray
}

$startMenuPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Programs)
if ($startMenuPath -and (Test-Path $startMenuPath)) {
    $startShortcutPath = Join-Path $startMenuPath "WinScreenLens.lnk"
    $startShortcut = $WshShell.CreateShortcut($startShortcutPath)
    $startShortcut.TargetPath = $pythonw
    $startShortcut.Arguments = "`"$runPy`""
    $startShortcut.WorkingDirectory = $targetDir
    $startShortcut.Description = "WinScreenLens - Screen Translator and Pronunciation Engine"
    if (Test-Path $iconPath) {
        $startShortcut.IconLocation = "$iconPath,0"
    }
    $startShortcut.WindowStyle = 7
    $startShortcut.Save()
    Write-Host "  -> Created Start Menu Shortcut: $startShortcutPath" -ForegroundColor Gray
}

Write-Host "[3/4] Creating Uninstaller..." -ForegroundColor Green
$lines = @(
    "@echo off",
    "echo Uninstalling WinScreenLens...",
    'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq WinScreenLens*" >nul 2>&1',
    'del /F /Q "%USERPROFILE%\Desktop\WinScreenLens.lnk" >nul 2>&1',
    'del /F /Q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\WinScreenLens.lnk" >nul 2>&1',
    "echo Shortcuts removed.",
    "if exist `"$targetDir`" (",
    "    echo To completely remove files, delete: $targetDir",
    ")",
    "echo WinScreenLens has been uninstalled.",
    "pause"
)
$uninstallerPath = Join-Path $targetDir "Uninstall_WinScreenLens.bat"
[System.IO.File]::WriteAllLines($uninstallerPath, $lines)

Write-Host "[4/4] Installation Complete!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " WinScreenLens is successfully installed!" -ForegroundColor Green
Write-Host "  * You can now launch it from your Desktop or Start Menu." -ForegroundColor White
Write-Host "  * Press Alt + W to look up words, Alt + Q for subtitles." -ForegroundColor White
Write-Host "  * Press Esc at any time to close overlays." -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
