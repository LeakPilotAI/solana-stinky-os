@echo off
setlocal EnableExtensions
title GENESIS
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
echo.
echo   GENESIS
echo   Project: %~dp0
echo   Closing this window does NOT stop Genesis services.
echo.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-stinky.ps1" %*
set "ERR=%ERRORLEVEL%"
echo.
if not "%ERR%"=="0" (
  echo   GENESIS STARTUP FAILED  exit %ERR%
  echo   Component / status / error are above.
  echo   Log: %~dp0logs\startup.log
  echo   This window stays open so you can copy the failure.
) else (
  echo   Genesis is running in the background.
  echo   Operator:  http://127.0.0.1:3000/operator
  echo   Stop:      double-click Stop Genesis
  echo   Closing this window will NOT stop Genesis.
)
echo.
pause
endlocal
exit /b %ERR%
