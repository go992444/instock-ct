@echo off
setlocal
cd /d "%~dp0"
title Instock CT Server

set "PY=%~dp0.venv\Scripts\python.exe"
set "PORT=8501"
set "LOG=%~dp0run-instock.log"

>>"%LOG%" echo === Instock CT %date% %time% ===

if not exist "%PY%" (
  >>"%LOG%" echo ERROR: venv missing at %PY%
  echo ERROR: .venv not found. Run run-instock.bat once to create it.
  exit /b 1
)

netstat -ano | findstr ":%PORT% " | findstr "LISTENING" >nul
if not errorlevel 1 (
  >>"%LOG%" echo Port %PORT% already listening
  exit /b 0
)

>>"%LOG%" echo Starting Streamlit on port %PORT%
"%PY%" -m pip install -r requirements.txt -q >>"%LOG%" 2>&1
if errorlevel 1 (
  >>"%LOG%" echo ERROR: pip install failed
  exit /b 1
)

>>"%LOG%" echo Launching streamlit...
"%PY%" -m streamlit run streamlit_app.py --server.port %PORT% >>"%LOG%" 2>&1
>>"%LOG%" echo Streamlit exited with code %errorlevel%
exit /b %errorlevel%
