@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PGPASSWORD=stinky"

echo [backup] checking Docker engine...
docker version >nul 2>nul
if errorlevel 1 (
  echo {"status":"FAIL","error":"docker_engine_unavailable","source_database_modified":false,"restored_over_source":false}
  echo.
  echo Genesis backup certification FAILED.
  echo Docker Desktop is not reachable. Start or restart Docker Desktop and rerun Backup-Genesis.cmd.
  exit /b 1
)

echo [backup] ensuring Genesis Postgres is running...
docker compose -p project-genesis up -d postgres
if errorlevel 1 (
  echo {"status":"FAIL","error":"postgres_start_failed","source_database_modified":false,"restored_over_source":false}
  echo.
  echo Genesis backup certification FAILED.
  echo Could not start the Genesis Postgres service.
  exit /b 1
)

echo [backup] waiting for stinky-postgres to become healthy...
set "READY=0"
for /L %%I in (1,1,36) do (
  for /f "usebackq delims=" %%H in (`docker inspect stinky-postgres --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" 2^>nul`) do set "DBHEALTH=%%H"
  if /I "!DBHEALTH!"=="healthy" (
    set "READY=1"
    goto :postgres_ready
  )
  timeout /t 5 /nobreak >nul
)

:postgres_ready
if not "%READY%"=="1" (
  echo {"status":"FAIL","error":"postgres_not_healthy","source_database_modified":false,"restored_over_source":false}
  echo.
  echo Genesis backup certification FAILED.
  echo stinky-postgres did not become healthy within 180 seconds.
  docker ps -a --filter "name=stinky-postgres"
  docker logs --tail 80 stinky-postgres 2>nul
  exit /b 1
)

echo [backup] stinky-postgres is healthy.
"%PY%" "%~dp0scripts\genesis_postgres_backup.py" certify --mode docker-network --container stinky-postgres --discover-container-endpoint --network project-genesis_default --db-host postgres --port 5432 --user stinky --password stinky --database stinky --output-dir "%~dp0backups"
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
