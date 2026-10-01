@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" "%~dp0scripts\paper_recovery_soak.py"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Genesis bounded paper recovery soak FAILED.
  echo See logs\diagnostics\paper-recovery-soak-*.json
  exit /b %ERR%
)
echo.
echo Genesis bounded paper recovery soak PASSED.
exit /b 0
