#Requires -Version 5.1
# Publish the native Heirloom WinUI studio (self-contained win-x64).
# Does not steal focus. Output: desktop/dist/Heirloom

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root "Heirloom\Heirloom.csproj"
$out = Join-Path $root "dist\Heirloom"

dotnet publish $project -c Release -r win-x64 --self-contained true -o $out /p:WindowsPackageType=None /p:PublishTrimmed=false
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }

$bat = Join-Path $out "Heirloom.bat"
@"
@echo off
start "" "%~dp0Heirloom.exe"
"@ | Set-Content -Path $bat -Encoding ASCII

Write-Output "Published $out"
Write-Output "Run Heirloom.exe (AppUserModelID UnboundInfotech.Heirloom). Paste the device token in Settings."
