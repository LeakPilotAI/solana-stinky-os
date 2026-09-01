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
rem pythonw + START /B: no extra consoles. Breaks away from the Explorer job.
if exist "%PYW%" (
  start "genesis-%NAME%" /B "%PYW%" "%~dp0run_genesis_service.py" --name "%NAME%"
) else (
  start "genesis-%NAME%" /B "%PY%" "%~dp0run_genesis_service.py" --name "%NAME%"
)
exit /b 0
