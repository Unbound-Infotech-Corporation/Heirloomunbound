# Smoke check for the Windows PC.
# Builds desktop/Heirloom (WinUI 3, .NET 8) and runs desktop/Heirloom.Tests.
# The agent that added this script cannot run it. A pass or fail here is
# only meaningful on the owner's Windows machine.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$buildProj = Join-Path $root "desktop/Heirloom/Heirloom.csproj"
$testProj = Join-Path $root "desktop/Heirloom.Tests/Heirloom.Tests.csproj"
$failed = @()

Write-Host "Building desktop/Heirloom (WinUI 3, .NET 8)..."
& dotnet build $buildProj -c Release
if ($LASTEXITCODE -ne 0) {
    $failed += "build"
}

Write-Host "Running desktop/Heirloom.Tests..."
& dotnet test $testProj -c Release --nologo
if ($LASTEXITCODE -ne 0) {
    $failed += "tests"
}

if ($failed.Count -eq 0) {
    Write-Host "PASS: WinUI build and dotnet tests succeeded."
    exit 0
}

Write-Host ("FAIL: " + ($failed -join ", "))
exit 1
