@echo off
cd /d "%~dp0"
title Instock CT

set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
  echo Creating venv...
  py -3 -m venv .venv 2>nul
  if not exist "%PY%" python -m venv .venv
  if not exist "%PY%" (
    echo ERROR: Python not found. Install from python.org
    pause
    exit /b 1
  )
)

echo Installing packages...
"%PY%" -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo ERROR: pip install failed
  pause
  exit /b 1
)

set PORT=8501
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo.
  echo Instock CT is already running on port %PORT%.
  start "" "http://localhost:%PORT%"
  echo Opened browser. You can close this window.
  echo.
  pause
  exit /b 0
)

:run
echo.
echo Instock CT - open http://localhost:%PORT%
echo Press Ctrl+C to stop
echo.
"%PY%" -m streamlit run streamlit_app.py --server.port %PORT%
pause