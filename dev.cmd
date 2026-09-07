@echo off
set "PATH=C:\Users\Administrator\AppData\Local\Programs\Python\Python312;C:\Users\Administrator\AppData\Local\Programs\Python\Python312\Scripts;C:\Users\Administrator\AppData\Local\Programs\Python\Python313;C:\Users\Administrator\AppData\Local\Programs\Python\Python313\Scripts;%PATH%"
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

netstat -ano | findstr ":8501 " | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo.
  echo WARNING: Port 8501 is already in use.
  echo Run stop-instock.bat first, then retry dev.cmd
  echo.
  pause
  exit /b 1
)

echo Installing packages...
"%PY%" -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo ERROR: pip install failed
  pause
  exit /b 1
)

echo.
echo Instock CT dev - http://localhost:8501
echo Press Ctrl+C to stop
echo.
"%PY%" -m streamlit run streamlit_app.py --server.port 8501
