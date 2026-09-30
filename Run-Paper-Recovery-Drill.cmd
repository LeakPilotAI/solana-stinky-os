@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0scripts\paper_recovery_drill.py"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Genesis paper-worker recovery drill FAILED.
  echo See logs\diagnostics\paper-recovery-drill-*.json
  exit /b %ERR%
)
echo.
echo Genesis paper-worker recovery drill PASSED.
exit /b 0
