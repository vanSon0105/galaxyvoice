$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $projectDir "Galaxy Studio.bat"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Galaxy AI Voice & Subtitle Studio.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Galaxy AI Voice & Subtitle Studio"
$shortcut.Save()

Write-Host "Created shortcut: $shortcutPath"
