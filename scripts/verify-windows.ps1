# Smoke check for the Windows PC and for GitHub Actions (windows-latest).
# Builds desktop/Heirloom (WinUI 3, .NET 8, x64) and runs desktop/Heirloom.Tests.
# Pass -ResultsDir to also write a TRX log. The script does not claim a pass
# from any machine that did not run it.
param(
    [string]$ResultsDir = ""
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$buildProj = Join-Path $root "desktop/Heirloom/Heirloom.csproj"
$testProj = Join-Path $root "desktop/Heirloom.Tests/Heirloom.Tests.csproj"
$failed = @()

Write-Host "Building desktop/Heirloom (WinUI 3, .NET 8, win-x64)..."
& dotnet build $buildProj -c Release -r win-x64
if ($LASTEXITCODE -ne 0) {
    $failed += "build"
}

Write-Host "Running desktop/Heirloom.Tests..."
$testArgs = @("test", $testProj, "-c", "Release", "--nologo")
if ($ResultsDir) {
    New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null
    $testArgs += @("--logger", "trx;LogFileName=heirloom-tests.trx", "--results-directory", (Join-Path $root $ResultsDir))
}
& dotnet @testArgs
if ($LASTEXITCODE -ne 0) {
    $failed += "tests"
}

if ($failed.Count -eq 0) {
    Write-Host "PASS: WinUI build and dotnet tests succeeded."
    exit 0
}

Write-Host ("FAIL: " + ($failed -join ", "))
exit 1
