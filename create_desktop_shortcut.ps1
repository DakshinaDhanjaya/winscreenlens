$desktop = [System.IO.Path]::Combine($env:USERPROFILE, "Desktop")
if (-not (Test-Path $desktop)) {
    $desktop = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
}
if (-not (Test-Path $desktop)) {
    $desktop = "$env:HOMEDRIVE$env:HOMEPATH\Desktop"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }

$ShortcutPath = [System.IO.Path]::Combine($desktop, "WinScreenLens.lnk")
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

$pythonw = [System.IO.Path]::Combine($scriptDir, ".venv\Scripts\pythonw.exe")
$runPy = [System.IO.Path]::Combine($scriptDir, "run.py")
$iconPath = [System.IO.Path]::Combine($scriptDir, "app\assets\app_icon.ico")

$Shortcut.TargetPath = $pythonw
$Shortcut.Arguments = "`"$runPy`""
$Shortcut.WorkingDirectory = $scriptDir
$Shortcut.Description = "WinScreenLens — Screen Translator & Pronunciation Engine"
if (Test-Path $iconPath) {
    $Shortcut.IconLocation = "$iconPath,0"
}
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "Created Desktop Shortcut successfully at: $ShortcutPath"
