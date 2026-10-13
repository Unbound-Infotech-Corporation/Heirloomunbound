# Build the Heirloom Twin Box autoinstall ISO from Windows.
# This script never writes a USB disk. It asks WSL to run box/autoinstall/build-usb.sh,
# which writes a .iso file. Flash that file with Rufus (DD Image mode) or balenaEtcher.
# Boot the stick only on the Twin Box.
[CmdletBinding()]
param(
    [string]$Config = "",
    [string]$Output = "",
    [string]$Iso = "",
    [string]$KernelExtra = ""
)

$ErrorActionPreference = "Stop"

function Refuse-DevicePath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }
    $lower = $Path.ToLowerInvariant()
    if ($lower -match '^[a-z]:\\?$' -or $lower.StartsWith("\\.\") -or $lower.StartsWith("//./") -or $lower.StartsWith("/dev/")) {
        throw "Refusing to write '$Path'. This script only builds an .iso file. Flash it with Rufus or balenaEtcher."
    }
    if (-not $lower.EndsWith(".iso")) {
        throw "Output must be a .iso file path, not '$Path'."
    }
}

Refuse-DevicePath $Output
Refuse-DevicePath $Iso

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoWin = (Resolve-Path (Join-Path $here "..\..")).Path

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-Error "WSL is not installed. Install WSL, then run: bash box/autoinstall/build-usb.sh"
    exit 1
}

$repoWsl = (& wsl.exe wslpath -a $repoWin).Trim()
if ([string]::IsNullOrWhiteSpace($repoWsl)) {
    throw "Could not convert $repoWin to a WSL path."
}

$bashArgs = @("box/autoinstall/build-usb.sh")
if ($Config) {
    Refuse-DevicePath $Config
    $configWsl = (& wsl.exe wslpath -a (Resolve-Path $Config)).Trim()
    $bashArgs += @("--config", $configWsl)
}
if ($Output) {
    $outParent = Split-Path -Parent $Output
    if (-not (Test-Path $outParent)) {
        New-Item -ItemType Directory -Path $outParent | Out-Null
    }
    $outputWsl = (& wsl.exe wslpath -a $Output).Trim()
    Refuse-DevicePath $outputWsl
    $bashArgs += @("--output", $outputWsl)
}
if ($Iso) {
    $isoWsl = (& wsl.exe wslpath -a (Resolve-Path $Iso)).Trim()
    Refuse-DevicePath $isoWsl
    $bashArgs += @("--iso", $isoWsl)
}
if ($KernelExtra) {
    $bashArgs += @("--kernel-extra", $KernelExtra)
}

Write-Host "BOOT THIS USB ONLY ON THE TWIN BOX."
Write-Host "Building the ISO through WSL. No USB device is written."

$quoted = $bashArgs | ForEach-Object {
    "'" + ($_ -replace "'", "'\''") + "'"
}
$command = "cd '$repoWsl' && bash $($quoted -join ' ')"
& wsl.exe -e bash -lc $command
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Flash the ISO with Rufus in DD Image mode, or with balenaEtcher."
Write-Host "Do not boot it on any PC except the Twin Box."
