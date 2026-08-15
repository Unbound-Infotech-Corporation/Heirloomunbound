@echo off
setlocal EnableDelayedExpansion
title Heirloom
cd /d "%~dp0"

set "INSTALL_DIR=%LOCALAPPDATA%\Heirloom"
set "APP_DIR=%INSTALL_DIR%\app"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "LOG=%INSTALL_DIR%\setup.log"
set "PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "PYV=%VENV_DIR%\Scripts\python.exe"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%APP_DIR%" mkdir "%APP_DIR%"

echo.>> "%LOG%"
echo Heirloom setup %DATE% %TIME%>> "%LOG%"

xcopy /S /E /Y /Q "%~dp0heirloom" "%APP_DIR%\heirloom\" >nul
if exist "%~dp0requirements.txt" copy /Y "%~dp0requirements.txt" "%INSTALL_DIR%\requirements.txt" >nul
if exist "%~dp0README.txt" copy /Y "%~dp0README.txt" "%INSTALL_DIR%\README.txt" >nul

set "NEED_DEPS=0"
if not exist "%PYW%" set "NEED_DEPS=1"
if not exist "%INSTALL_DIR%\requirements.ok" set "NEED_DEPS=1"
if exist "%INSTALL_DIR%\requirements.txt" if exist "%INSTALL_DIR%\requirements.ok" (
  fc /b "%INSTALL_DIR%\requirements.txt" "%INSTALL_DIR%\requirements.ok" >nul 2>&1
  if errorlevel 1 set "NEED_DEPS=1"
)
if exist "%PYV%" (
  "%PYV%" -c "import PySide6, requests, PIL" >> "%LOG%" 2>&1
  if errorlevel 1 set "NEED_DEPS=1"
)

if "%NEED_DEPS%"=="1" (
  echo Setting up Heirloom for the first time — about a minute.
  echo Leave this window open.
  echo.
  call :ensure_python
  if errorlevel 1 (
    echo.
    echo Python is missing. Heirloom tried to install it.
    echo If a box appeared, finish it, then double-click Heirloom.bat again.
    echo Details: %LOG%
    pause
    exit /b 1
  )
  if not exist "%PYV%" (
    echo Preparing a private Python folder...
    if defined PY_LAUNCHER (
      py -3 -m venv "%VENV_DIR%" >> "%LOG%" 2>&1
    ) else (
      "%PY_CMD%" -m venv "%VENV_DIR%" >> "%LOG%" 2>&1
    )
    if errorlevel 1 (
      echo Couldn't prepare Heirloom. Check your internet and try again.
      echo Details: %LOG%
      pause
      exit /b 1
    )
  )
  echo Installing Heirloom...
  "%PYV%" -m pip install --upgrade pip >> "%LOG%" 2>&1
  "%PYV%" -m pip install -r "%INSTALL_DIR%\requirements.txt" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo Install didn't finish. Check your internet, then double-click Heirloom.bat again.
    echo Details: %LOG%
    pause
    exit /b 1
  )
  "%PYV%" -c "import PySide6, requests, PIL" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo Heirloom didn't finish installing. Double-click Heirloom.bat to try again.
    echo Details: %LOG%
    pause
    exit /b 1
  )
  copy /Y "%INSTALL_DIR%\requirements.txt" "%INSTALL_DIR%\requirements.ok" >nul
)

if not exist "%PYW%" (
  echo Heirloom isn't ready yet. Double-click Heirloom.bat again.
  echo Details: %LOG%
  pause
  exit /b 1
)

cd /d "%APP_DIR%"
start "" "%PYW%" -m heirloom
endlocal
exit /b 0

:ensure_python
set "PY_CMD="
set "PY_LAUNCHER="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "PY_LAUNCHER=1"
  exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY_CMD=python"
    exit /b 0
  )
)
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
  if exist "%%~P" (
    set "PY_CMD=%%~P"
    exit /b 0
  )
)

echo Python isn't on this computer yet. Installing it now...
where winget >nul 2>nul
if errorlevel 1 (
  echo Opening the Python download page. Tick "Add python.exe to PATH", then run Heirloom.bat again.
  start "" "https://www.python.org/downloads/"
  echo Opened Python download because winget is missing>> "%LOG%"
  exit /b 1
)
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  exit /b 0
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PY_LAUNCHER=1"
  exit /b 0
)
echo Python install did not finish. Open https://www.python.org/downloads/ — tick Add python.exe to PATH — then run Heirloom.bat again.
echo winget Python install did not produce python.exe>> "%LOG%"
exit /b 1
