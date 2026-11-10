#Requires -Version 5.1
# Hidden start when Windows signs in. Pass -Disable to remove it.
param([switch]$Disable)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "Heirloom Study Hall.lnk"
if ($Disable) {
    if (Test-Path $link) { Remove-Item $link -Force }
    Write-Output "Study Hall will not start at sign-in."
    exit 0
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\Start-StudyHall.ps1`" -Hidden"
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "Heirloom Study Hall"
$shortcut.Save()
Write-Output "Study Hall will start hidden at sign-in."
