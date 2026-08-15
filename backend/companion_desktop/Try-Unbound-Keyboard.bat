@echo off
setlocal
title Unbound Keyboard
cd /d "%~dp0"

echo.
echo  Unbound Keyboard
echo.
echo  First time takes about a minute. Leave this window open.
echo  If Windows shows a blue box: More info, then Run anyway.
echo.
echo  When the writing card opens, type:
echo    I recieve this and should of said thanks just just just
echo.
echo  We never ask for a Windows password.
echo.

set "HEIRLOOM_TRY_KEYBOARD=1"
call "%~dp0Heirloom.bat"
endlocal
