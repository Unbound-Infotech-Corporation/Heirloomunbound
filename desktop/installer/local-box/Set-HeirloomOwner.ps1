#Requires -Version 5.1
# Choose or change the owner sign-in for Heirloom on this PC. The password is stored only as a scrypt hash.
[CmdletBinding()]
param([string]$InstallDir = $PSScriptRoot, [Parameter(Mandatory = $true)][string]$Email)
$py = Join-Path $InstallDir "venv\Scripts\python.exe"
Push-Location (Join-Path $InstallDir "app\backend")
try { & $py -m local_box set-owner --data (Join-Path $InstallDir "data") --email $Email } finally { Pop-Location }
