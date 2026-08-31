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
if exist "%PY%" goto :runpy
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3.12 "%~dp0start_genesis.py" %*
  goto :after
)
where python >nul 2>&1
if %ERRORLEVEL%==0 (
  python "%~dp0start_genesis.py" %*
  goto :after
)
echo   Python 3.12+ not found. Install python.org 3.12, then double-click Genesis again.
set "ERR=1"
goto :done

:runpy
"%PY%" "%~dp0start_genesis.py" %*

:after
set "ERR=%ERRORLEVEL%"

:done
echo.
if not "%ERR%"=="0" (
  echo   GENESIS STARTUP FAILED  exit %ERR%
  echo   Component / status / error are above.
  echo   Log: %~dp0logs\startup.log
  echo   This window stays open so you can copy the failure.
) else (
  echo   Genesis is running in the background.
  echo   Operator:  http://127.0.0.1:3000/operator
  echo   Stop:      double-click Stop Genesis
  echo   Closing this window will NOT stop Genesis.
)
echo.
pause
endlocal
exit /b %ERR%
