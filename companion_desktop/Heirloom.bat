@echo off
setlocal EnableDelayedExpansion
title Heirloom
:: Hide this console after launch — pythonw runs the GUI without a window

set "INSTALL_DIR=%LOCALAPPDATA%\Heirloom"
set "APP_DIR=%INSTALL_DIR%\app"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "PY_EXE=%VENV_DIR%\Scripts\pythonw.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%APP_DIR%" mkdir "%APP_DIR%"

:: Copy source on first run (and any time files are newer)
xcopy /S /E /Y /Q "%~dp0heirloom" "%APP_DIR%\heirloom\" >nul

:: First-run: create venv + install deps
if not exist "%PY_EXE%" (
    echo Setting up Heirloom for the first time — this takes ~60 seconds...
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10+ is required but not found. Opening Python download...
        start "" "https://www.python.org/downloads/"
        echo After installing Python, re-run Heirloom.bat.
        pause
        exit /b 1
    )
    py -3 -m venv "%VENV_DIR%"
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
    "%PIP_EXE%" install -r "%~dp0requirements.txt" --quiet
)

:: Launch silently (no console window)
cd /d "%APP_DIR%"
start "" "%PY_EXE%" -m heirloom

endlocal
