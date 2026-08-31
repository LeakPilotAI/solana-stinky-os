@echo off
setlocal EnableExtensions
title GENESIS APPLY LAUNCHER
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
echo.
echo   Pull origin/main, remake Genesis.lnk
echo   Project: %~dp0
echo.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0APPLY-launcher.ps1" %*
echo.
pause
endlocal
