@echo off
title Study Terminal installer
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-app.ps1"
if errorlevel 1 (
  echo.
  echo Something went wrong. Send install-log.txt from this folder if you need help.
  pause
  exit /b 1
)
echo.
echo You can close this window.
timeout /t 15
