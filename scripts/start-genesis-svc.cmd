@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "NAME=%~1"
if "%NAME%"=="" (
  echo missing service name
  exit /b 1
)
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"
rem cmd START creates a new console and breaks away from the Explorer job object.
start "genesis-%NAME%" /MIN "%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-genesis-service.ps1" -Name "%NAME%"
exit /b 0
