@echo off
title GENESIS STOP
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-stinky.ps1"
