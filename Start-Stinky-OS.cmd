@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
 echo Existing Python environment missing. Recovery will not install or reset evidence.
 set "ERR=1"
 goto :done
)
if "%~1"=="" (
 "%PY%" "%~dp0start_genesis.py" --core-only
) else (
 "%PY%" "%~dp0start_genesis.py" %*
)
set "ERR=%ERRORLEVEL%"
:done
if not "%ERR%"=="0" (
 echo GENESIS STARTUP FAILED. See logs\startup.log. Existing services are untouched.
) else (
 echo Genesis verified running. Closing this window will NOT stop Genesis.
 echo Command Center: http://127.0.0.1:3000/command-center
)
pause
endlocal & exit /b %ERR%
