@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "NAME=%~1"
if "%NAME%"=="" (
  echo missing service name
  exit /b 1
)
set "PY=%CD%\.venv\Scripts\python.exe"
set "PYW=%CD%\.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
  echo missing venv python
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
rem No `start` — Windows Terminal turns every START into a new window.
rem pythonw has no console. Watchdog/desktop must not pile cmd windows.
if exist "%PYW%" (
  "%PYW%" "%~dp0run_genesis_service.py" --name "%NAME%"
) else (
  "%PY%" "%~dp0run_genesis_service.py" --name "%NAME%"
)
exit /b 0
