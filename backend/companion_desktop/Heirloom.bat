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
copy /Y "%~dp0requirements.txt" "%APP_DIR%\requirements.txt" >nul

:: Resolve a Python launcher: prefer `py -3`, fall back to `python`
set "PY_LAUNCH="
where py >nul 2>nul
if not errorlevel 1 set "PY_LAUNCH=py -3"
if not defined PY_LAUNCH (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_LAUNCH=python"
)

:: First-run: create venv + install deps
if not exist "%PY_EXE%" (
    echo Setting up Heirloom for the first time — this takes ~60 seconds...
    if not defined PY_LAUNCH (
        echo Python 3.10+ is required but not found. Opening Python download...
        start "" "https://www.python.org/downloads/"
        echo After installing Python, re-run Heirloom.bat.
        pause
        exit /b 1
    )
    %PY_LAUNCH% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtualenv.
        pause
        exit /b 1
    )
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip --quiet
    "%PIP_EXE%" install -r "%APP_DIR%\requirements.txt"
    if errorlevel 1 (
        echo Dependency install failed — retrying without quiet mode...
        "%PIP_EXE%" install -r "%APP_DIR%\requirements.txt"
        if errorlevel 1 (
            echo Could not install dependencies. Check your internet connection.
            pause
            exit /b 1
        )
    )
) else (
    :: Soft-upgrade deps when requirements.txt changes (idempotent, quiet)
    "%PIP_EXE%" install -r "%APP_DIR%\requirements.txt" --quiet >nul 2>nul
)

:: Launch silently (no console window)
cd /d "%APP_DIR%"
start "" "%PY_EXE%" -m heirloom

endlocal
