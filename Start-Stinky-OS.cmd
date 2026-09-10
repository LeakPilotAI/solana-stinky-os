@echo off
setlocal EnableExtensions
title GENESIS
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo.
echo   GENESIS
echo   Project: %~dp0
echo   Closing this window does NOT stop Genesis services.
echo.

set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto :preflight
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=py -3.12"
  goto :preflight
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  set "PY=python"
  goto :preflight
)
echo   Python 3.12+ not found. Install python.org 3.12, then double-click Genesis again.
set "ERR=1"
goto :done

:preflight
echo   Running strict schema gate before application services...
%PY% "%~dp0scripts\strict_startup_schema_gate.py"
if not "%ERRORLEVEL%"=="0" (
  set "ERR=%ERRORLEVEL%"
  goto :done
)

echo   Strict schema gate passed. Starting Genesis services...
%PY% "%~dp0start_genesis.py" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" goto :done

echo   Starting persistent paper-only runtime...
%PY% "%~dp0scripts\start_paper_runtime.py"
if not "%ERRORLEVEL%"=="0" (
  set "ERR=%ERRORLEVEL%"
  goto :done
)

:done
echo.
if not "%ERR%"=="0" (
  echo   GENESIS STARTUP FAILED  exit %ERR%
  echo   Component / status / error are above.
  echo   Log: %~dp0logs\startup.log
  echo   This window stays open so you can copy the failure.
) else (
  echo   Genesis is running in the background.
  echo   Paper runtime: ACTIVE, evidence-only, no RPC/signing/orders.
  echo   Operator:  http://127.0.0.1:3000/operator
  echo   Stop:      double-click Stop Genesis
  echo   Closing this window will NOT stop Genesis.
)
echo.
pause
echo   Window stays open. Press any key again to close.
pause
endlocal
exit /b 0
