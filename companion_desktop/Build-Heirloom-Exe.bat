@echo off
:: Build Heirloom.exe (Windows) — single-folder, no SmartScreen signing.
:: Run on a Windows machine that has Python 3.10+. Produces dist\Heirloom\.

setlocal EnableDelayedExpansion
title Heirloom · Build EXE

if not exist "%~dp0heirloom\__main__.py" (
  echo Run this from the companion_desktop directory.
  pause
  exit /b 1
)

set "BUILD_DIR=%~dp0_build"
set "VENV=%BUILD_DIR%\venv"

echo === Heirloom EXE build ===
echo  Output:        %~dp0dist\Heirloom\Heirloom.exe
echo  Build venv:    %VENV%
echo.

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

:: 1) venv
if not exist "%VENV%\Scripts\python.exe" (
  echo [1/4] Creating build venv...
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ is required but `py` was not found. Install Python from python.org and re-run.
    pause
    exit /b 1
  )
  py -3 -m venv "%VENV%"
)

:: 2) install deps + pyinstaller
echo [2/4] Installing dependencies + PyInstaller...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%VENV%\Scripts\pip.exe" install -r "%~dp0requirements.txt" --quiet
"%VENV%\Scripts\pip.exe" install pyinstaller --quiet

:: 3) clean previous build
echo [3/4] Cleaning previous build...
if exist "%~dp0build" rmdir /S /Q "%~dp0build"
if exist "%~dp0dist"  rmdir /S /Q "%~dp0dist"

:: 4) run PyInstaller against the spec
echo [4/4] Running PyInstaller (3-5 minutes)...
pushd "%~dp0"
"%VENV%\Scripts\pyinstaller.exe" heirloom.spec --clean --noconfirm
set RC=%ERRORLEVEL%
popd

if not "%RC%"=="0" (
  echo.
  echo Build failed (exit %RC%). Check the PyInstaller output above.
  pause
  exit /b %RC%
)

echo.
echo === BUILD COMPLETE ===
echo  EXE:  %~dp0dist\Heirloom\Heirloom.exe
echo  Size: 
for /f "tokens=*" %%S in ('powershell -command "(Get-ChildItem '%~dp0dist\Heirloom' -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB"') do echo  Bundle: %%S MB
echo.
echo You can zip the entire 'dist\Heirloom\' folder and share it. SmartScreen
echo will warn on first run because the exe isn't code-signed — click
echo "More info" -^> "Run anyway" to launch. Once enough installs
echo accumulate, SmartScreen reputation kicks in automatically.
echo.
pause
endlocal
