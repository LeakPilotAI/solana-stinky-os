@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo [validation] checking Docker engine...
docker version >nul 2>nul
if errorlevel 1 (
  echo {"status":"FAIL","error":"docker_engine_unavailable","paper_only":true,"database_modified":false}
  echo Genesis formal paper validation preflight FAILED. Docker Desktop is not reachable.
  exit /b 1
)

echo [validation] ensuring Genesis Postgres is running...
docker compose -p project-genesis up -d postgres
if errorlevel 1 (
  echo {"status":"FAIL","error":"postgres_start_failed","paper_only":true,"database_modified":false}
  echo Genesis formal paper validation preflight FAILED. Could not start Genesis Postgres.
  exit /b 1
)

echo [validation] waiting for stinky-postgres to become healthy...
set "READY=0"
for /L %%I in (1,1,36) do (
  set "DBHEALTH="
  for /f "usebackq delims=" %%H in (`docker inspect stinky-postgres --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul`) do set "DBHEALTH=%%H"
  if /I "!DBHEALTH!"=="healthy" (
    set "READY=1"
    goto :postgres_ready
  )
  timeout /t 5 /nobreak >nul
)
:postgres_ready
if not "%READY%"=="1" (
  echo {"status":"FAIL","error":"postgres_not_healthy","paper_only":true,"database_modified":false}
  echo Genesis formal paper validation preflight FAILED. stinky-postgres did not become healthy within 180 seconds.
  docker ps -a --filter "name=stinky-postgres"
  docker logs --tail 80 stinky-postgres 2>nul
  exit /b 1
)

echo [validation] stinky-postgres is healthy.
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
