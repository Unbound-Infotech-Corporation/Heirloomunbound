#Requires -Version 5.1
# Stop what Start-Heirloom started (API, voice, database). Ollama is left running: other apps may use it.
[CmdletBinding()]
param([string]$InstallDir = "")
# $PSScriptRoot is empty inside param() defaults on Windows PowerShell 5.1.
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$Pids = Join-Path $InstallDir "data\pids"
foreach ($name in "api", "voice", "mongod") {
  $file = Join-Path $Pids "$name.pid"
  if (-not (Test-Path $file)) { continue }
  $id = [int](Get-Content $file)
  $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
  # Only stop the process if it is still the one we started from this folder.
  if ($proc -and $proc.Path -and $proc.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase)) {
    # The venv python.exe is a launcher; stop its child too.
    & taskkill.exe /T /F /PID $id | Out-Null
    Write-Host "Stopped $name ($id)."
  }
  Remove-Item $file -Force
}
