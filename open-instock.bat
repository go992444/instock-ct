@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PORT=8501"
set "URL=http://localhost:%PORT%"

netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  echo Instock CT starting in background...
  start "" /min "%~dp0_run-instock-core.bat"
  timeout /t 4 /nobreak >nul
)

start "" "%URL%"
echo Opened %URL%
echo If the page is blank, wait a few seconds and refresh.
timeout /t 3 /nobreak >nul
