@echo off
:: Build HeirloomUnboundSetup.exe on Windows.
:: 1) Publish WinUI (or reuse desktop\dist\Heirloom-ready)
:: 2) Compile desktop\installer\HeirloomUnbound.iss with Inno Setup 6
:: SmartScreen will warn: this Setup is unsigned. More info → Run anyway.

setlocal EnableDelayedExpansion
title Heirloom Unbound · Build Setup.exe

set "ROOT=%~dp0..\.."
set "DESKTOP=%~dp0.."
set "ISS=%~dp0HeirloomUnbound.iss"
set "DIST=%DESKTOP%\dist\Heirloom-ready"
set "ISCC="

echo === Heirloom Unbound Setup ===
echo  Script: %ISS%
echo  App bits: %DIST%
echo.

if /I "%1"=="--skip-publish" goto :find_iscc

if exist "%DESKTOP%\Heirloom\Heirloom.csproj" (
  echo [1/3] Publishing WinUI studio…
  dotnet publish "%DESKTOP%\Heirloom\Heirloom.csproj" -c Release -r win-x64 --self-contained true -o "%DIST%" /p:WindowsPackageType=None /p:PublishTrimmed=false
  if errorlevel 1 (
    echo Publish failed. If Heirloom.exe is locked, quit the running app and retry.
    echo You can also pass --skip-publish when %DIST% already exists.
    exit /b 1
  )
) else (
  echo No WinUI project here — expecting a prebuilt folder at %DIST%
)

:find_iscc
if not exist "%DIST%\Heirloom.exe" (
  echo Missing %DIST%\Heirloom.exe
  echo Publish the WinUI app first, or copy a ready folder there.
  exit /b 1
)

echo [2/3] Finding Inno Setup 6…
for %%P in (
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
) do if exist %%~P set "ISCC=%%~P"

if "%ISCC%"=="" (
  echo Inno Setup 6 was not found.
  echo Install from https://jrsoftware.org/isdl.php then re-run this bat.
  echo The .iss sources stay in desktop\installer\ — Linux CI cannot produce Setup.exe.
  exit /b 2
)

echo [3/3] Compiling HeirloomUnboundSetup.exe…
"%ISCC%" /DDistDir="%DIST%" "%ISS%"
if errorlevel 1 (
  echo ISCC failed.
  exit /b 1
)

echo.
echo === BUILD COMPLETE ===
echo  Setup: %DESKTOP%\dist\HeirloomUnboundSetup.exe
echo.
echo SmartScreen will warn on first run because the exe is unsigned.
echo Choose More info → Run anyway. Reputation accumulates with installs.
echo.
endlocal
exit /b 0
