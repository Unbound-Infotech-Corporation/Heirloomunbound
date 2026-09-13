@echo off
:: Heirloom Unbound Setup — post-copy provisioner.
:: Reads the profile chosen in Setup, writes install_profile, then
:: launches the app or the Python CLI. Engine failures coach; they do
:: not abort Setup unless the app bits are missing.

setlocal EnableDelayedExpansion
title Heirloom Unbound · Provision

set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=medium"
if /I "%PROFILE%"=="lite" set "PROFILE=small"
if /I "%PROFILE%"=="full" set "PROFILE=medium"
if /I "%PROFILE%"=="max" set "PROFILE=large"
if /I "%PROFILE%"=="studio" set "PROFILE=large"

set "VAULT=%~2"
set "CONSENT=%~3"
set "APPDIR=%~4"
if "%APPDIR%"=="" set "APPDIR=%~dp0..\dist\Heirloom-ready"

set "DATA=%LOCALAPPDATA%\Heirloom"
if not exist "%DATA%" mkdir "%DATA%"

echo Heirloom Unbound · writing install_profile=%PROFILE%
> "%DATA%\install_profile.txt" echo %PROFILE%

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p='%DATA%\settings.json'; $prof='%PROFILE%'; $vault='%VAULT%';" ^
  "$o=@{}; if (Test-Path $p) { try { $o = Get-Content $p -Raw | ConvertFrom-Json } catch { $o=@{} } };" ^
  "if ($o -isnot [hashtable] -and $o.PSObject) { $h=@{}; $o.PSObject.Properties | ForEach-Object { $h[$_.Name]=$_.Value }; $o=$h };" ^
  "if ($o -isnot [hashtable]) { $o=@{} };" ^
  "$o.install_profile=$prof; $o.disk_profile=$prof; $o.space_profile=$prof;" ^
  "if ($prof -eq 'dedicated') { $o.machine_role='dedicated'; $o.dedicated_consent=$true; $o.warm_engines=$true; $o.live_listen=$true; $o.autostart=$true; $o.start_with_windows=$true; if ($vault) { $o.library_path=$vault; $o.vault_folder=$vault } };" ^
  "$o | ConvertTo-Json -Depth 8 | Set-Content $p -Encoding UTF8"

echo install_profile written to %DATA%\settings.json

if exist "%APPDIR%\Heirloom.exe" (
  echo Launching Heirloom Unbound…
  start "" "%APPDIR%\Heirloom.exe"
  exit /b 0
)

set "COMPANION=%~dp0..\..\backend\companion_desktop"
if exist "%COMPANION%\heirloom\provision_cli.py" (
  where py >nul 2>nul
  if not errorlevel 1 (
    echo Running companion provision CLI…
    pushd "%COMPANION%"
    if /I "%PROFILE%"=="dedicated" (
      py -3 -m heirloom.provision_cli --profile dedicated --vault "%VAULT%" --consent --start-with-windows
    ) else (
      py -3 -m heirloom.provision_cli --profile %PROFILE%
    )
    set "RC=!ERRORLEVEL!"
    popd
    exit /b !RC!
  )
)

echo App bits are in. First launch of Heirloom Unbound will finish model downloads.
echo SmartScreen may warn because this Setup is unsigned — More info, Run anyway.
endlocal
exit /b 0
