@echo off
title GENESIS REFRESH
cd /d "%~dp0"
echo.
echo   Overwrite D:\Work\Project-Genesis from GitHub.
echo   .env is kept. Gate 1 stays $150k.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0APPLY-refresh.ps1"
pause
