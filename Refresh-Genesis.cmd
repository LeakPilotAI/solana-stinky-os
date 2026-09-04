@echo off
setlocal EnableExtensions
title GENESIS REFRESH
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
echo.
echo   Overwrite this folder from GitHub.
echo   .env is kept. Gate 1 is $33k / 5m, clamp $200k.
echo.
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0APPLY-refresh.ps1"
echo.
pause
endlocal
