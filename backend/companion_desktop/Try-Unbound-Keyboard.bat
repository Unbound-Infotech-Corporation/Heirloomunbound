@echo off
setlocal
title Heirloom
cd /d "%~dp0"

echo.
echo  Heirloom — the whole house
echo.
echo  This opens the full app, not only the writing card.
echo  First time takes about a minute. Leave this window open.
echo  If Windows shows a blue box: More info, then Run anyway.
echo.
echo  Tap Sign in with Google. Sign in in the browser.
echo  We never ask for a Google or Windows password.
echo.
echo  Unbound Keyboard is in the tray, or Ctrl+Shift+U.
echo  When that card opens, type:
echo    I recieve this and should of said thanks just just just
echo.

set "HEIRLOOM_TRY_KEYBOARD=1"
call "%~dp0Heirloom.bat"
endlocal
