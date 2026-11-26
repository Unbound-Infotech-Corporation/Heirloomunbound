#Requires -Version 5.1
# Heirloom self-test for beta testers: runs the tier suite for THIS PC's tier against the local install
# and writes a report you can send back. Uses made-up personas only; your own memories are never read
# or included. Takes 10-40 minutes depending on the graphics card.
#
#   powershell -ExecutionPolicy Bypass -File Heirloom-Selftest.ps1            # core, tools, life story
#   powershell -ExecutionPolicy Bypass -File Heirloom-Selftest.ps1 -Quick     # core and tools only
[CmdletBinding()]
param(
  [string]$InstallDir = "",
  [switch]$Quick,
  [switch]$Fallback
)
# $PSScriptRoot is empty inside param() defaults on Windows PowerShell 5.1.
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$ErrorActionPreference = "Stop"
$Data = Join-Path $InstallDir "data"
$py = Join-Path $InstallDir "venv\Scripts\python.exe"
if (-not (Test-Path (Join-Path $Data "heirloom.env"))) { throw "Heirloom is not set up in $InstallDir." }

# The suite talks to the local database and Ollama; make sure they are up.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDir "Start-Heirloom.ps1") -InstallDir $InstallDir -NoBrowser | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = Join-Path $Data "selftest\$stamp"
$suites = if ($Quick) { "core,tools" } else { "core,tools,life_story" }
$suiteArgs = @("-u", "-m", "tier_suite", "--tier", "auto", "--data", $Data, "--suites", $suites, "--out", $out)
if ($Fallback) { $suiteArgs += "--fallbacks" }

Write-Host "Heirloom self-test ($suites). This can take a while; leave this window open."
Push-Location (Join-Path $InstallDir "app\backend")
try { & $py @suiteArgs; $code = $LASTEXITCODE } finally { Pop-Location }

# A bundle to send back: the report, the hardware plan and the install log. Never heirloom.env,
# the database, the vault, or the API logs (those can hold your own words).
$bundleDir = Join-Path $out "bundle"
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
Copy-Item (Join-Path $out "report.md"), (Join-Path $out "results.json") $bundleDir -ErrorAction SilentlyContinue
Get-ChildItem (Join-Path $Data "logs") -Filter "install-*.log" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime | Select-Object -Last 1 | Copy-Item -Destination $bundleDir
Push-Location (Join-Path $InstallDir "app\backend")
try { & $py -m local_box plan --data $Data | Out-File -Encoding utf8 (Join-Path $bundleDir "hardware-plan.json") } finally { Pop-Location }
$zip = Join-Path $Data "selftest\heirloom-selftest-$stamp.zip"
Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zip -Force

Write-Host ""
if ($code -eq 0) { Write-Host "Self-test PASSED." } else { Write-Host "Self-test found problems (see the report)." }
Write-Host "Report: $(Join-Path $out 'report.md')"
Write-Host "Send this file with your beta feedback: $zip"
exit $code
