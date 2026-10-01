@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
docker version >nul 2>nul
if errorlevel 1 (
 echo Genesis prospective evidence report FAILED. Docker Desktop is not reachable.
 exit /b 1
)
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
if not "%READY%"=="1" (
 echo Genesis prospective evidence report FAILED. stinky-postgres did not become healthy within 180 seconds.
 exit /b 1
)
set "REPORT_OK=0"
for /L %%I in (1,1,3) do (
 "%PY%" "%~dp0scripts\report_prospective_evidence_accumulation.py"
 if not errorlevel 1 (
  set "REPORT_OK=1"
  goto :report_ok
 )
 if %%I LSS 3 (
  echo Genesis prospective evidence report attempt %%I failed; retrying in 3 seconds...
  timeout /t 3 /nobreak >nul
 )
)
echo Genesis prospective evidence report FAILED after 3 attempts.
exit /b 1

:report_ok
exit /b 0
