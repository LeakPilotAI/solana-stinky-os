@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PGPASSWORD=stinky"
"%PY%" "%~dp0scripts\genesis_postgres_backup.py" certify --mode docker --container stinky-postgres --host 127.0.0.1 --port 5433 --user stinky --password stinky --database stinky --output-dir "%~dp0backups"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Genesis backup certification FAILED.
  echo Canonical database was not restored over or replaced.
  exit /b %ERR%
)
echo.
echo Genesis backup + isolated restore certification PASSED.
exit /b 0
