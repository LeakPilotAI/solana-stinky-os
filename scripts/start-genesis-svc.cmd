@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "NAME=%~1"
if "%NAME%"=="" (
  echo missing service name
  exit /b 1
)
set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo missing venv python
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem cmd START creates a new console and breaks away from the Explorer job object.
start "genesis-%NAME%" /MIN "%PY%" "%~dp0run_genesis_service.py" --name "%NAME%"
exit /b 0
