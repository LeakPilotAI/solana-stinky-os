@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0scripts\formal_paper_validation_preflight.py"
set "ERR=%ERRORLEVEL%"
if "%ERR%"=="2" (
  echo.
  echo Genesis formal paper validation is NOT READY. This is a safe evidence result, not a launcher failure.
  exit /b 0
)
if not "%ERR%"=="0" exit /b %ERR%
echo.
echo Genesis formal paper validation preflight PASSED.
exit /b 0
