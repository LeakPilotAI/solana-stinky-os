@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
docker version >nul 2>nul
if errorlevel 1 exit /b 1
docker compose -p project-genesis up -d postgres
if errorlevel 1 exit /b 1
set "READY=0"
for /L %%I in (1,1,36) do (
 set "DBHEALTH="
 for /f "usebackq delims=" %%H in (`docker inspect stinky-postgres --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul`) do set "DBHEALTH=%%H"
 if /I "!DBHEALTH!"=="healthy" (set "READY=1"&goto :ready)
 timeout /t 5 /nobreak >nul
)
:ready
if not "%READY%"=="1" exit /b 1
"%PY%" "%~dp0scripts\diagnose_unresolved_prospective_outcomes.py"
exit /b %ERRORLEVEL%
