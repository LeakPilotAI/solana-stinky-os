@echo off
setlocal EnableExtensions
rem Manual read-only panel. No autostart or service lifecycle commands.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Genesis-Background-Panel.ps1"
endlocal
