@echo off
title GENESIS
cd /d "%~dp0"
echo.
echo   GENESIS
echo   Starting operator box...
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-stinky.ps1"
if errorlevel 1 (
  echo.
  echo   START FAILED. See logs\*.log
  pause
)
