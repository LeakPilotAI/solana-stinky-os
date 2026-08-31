@echo off
setlocal EnableExtensions
title GENESIS STOP
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
echo.
echo   GENESIS STOP
echo   Project: %~dp0
echo   Only Genesis-owned processes/containers are stopped.
echo.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-stinky.ps1" %*
set "ERR=%ERRORLEVEL%"
echo.
if not "%ERR%"=="0" (
  echo   GENESIS STOP FAILED  exit %ERR%
  echo   Log: %~dp0logs\startup.log
) else (
  echo   STOPPED. ATLAS and other local stacks were not targeted.
)
echo.
pause
endlocal
exit /b %ERR%
