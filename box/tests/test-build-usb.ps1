# Path policy for the Windows build wrapper. No WSL and no ISO are required.
$ErrorActionPreference = "Stop"
$env:HEIRLOOM_BUILD_USB_LIB_ONLY = "1"
. (Join-Path $PSScriptRoot "..\autoinstall\build-usb.ps1")

function Assert-Refused {
    param(
        [scriptblock]$Body,
        [string]$Needle
    )
    $threw = $false
    try {
        & $Body
    } catch {
        $threw = $true
        if ($_.Exception.Message -notlike "*${Needle}*") {
            throw "Expected '$Needle' in '$($_.Exception.Message)'"
        }
    }
    if (-not $threw) {
        throw "Expected a refusal from: $Body"
    }
}

# A Windows config.env is a file. The .iso rule must not reject it.
Refuse-RawDevicePath 'C:\Users\owner\config.env'
Refuse-RawDevicePath 'D:\TwinBox\box\autoinstall\config.env'
Refuse-IsoOutput 'D:\TwinBox\out\heirloom-twinbox-autoinstall.iso'

Assert-Refused { Refuse-RawDevicePath '/dev/sda' } 'Refusing to use'
Assert-Refused { Refuse-RawDevicePath '\\.\PhysicalDrive0' } 'Refusing to use'
Assert-Refused { Refuse-RawDevicePath '//./PhysicalDrive0' } 'Refusing to use'
Assert-Refused { Refuse-RawDevicePath 'E:\' } 'Refusing to use'
Assert-Refused { Refuse-RawDevicePath 'E:' } 'Refusing to use'
Assert-Refused { Refuse-IsoOutput 'C:\Users\owner\config.env' } 'must be a .iso'
Assert-Refused { Refuse-IsoOutput '/dev/sdb' } 'Refusing to use'

Write-Host "build-usb.ps1 ok"
