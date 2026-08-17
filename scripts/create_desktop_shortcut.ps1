$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start_planning_ai.ps1"
$icon = Join-Path $projectRoot "assets\planning-ai.ico"
$desktop = [Environment]::GetFolderPath("DesktopDirectory")
$shortcutPath = Join-Path $desktop "Prometheus Planning AI.lnk"

if (-not (Test-Path -LiteralPath $launcher)) { throw "Launcher not found: $launcher" }
if (-not (Test-Path -LiteralPath $icon)) { throw "Icon not found: $icon" }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = "Open the private local Prometheus Planning AI assistant"
$shortcut.Save()

Write-Output $shortcutPath
