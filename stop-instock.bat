@echo off
cd /d "%~dp0"
title Stop Instock CT

echo Stopping Streamlit on ports 8501-8510...
set stopped=0
for /L %%P in (8501,1,8510) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
    echo   Killing PID %%A on port %%P
    taskkill /PID %%A /F >nul 2>&1
    set stopped=1
  )
)

if "%stopped%"=="0" (
  echo No Streamlit listener found on 8501-8510.
) else (
  echo Done. Close browser tabs for localhost:8501 etc.
)
pause
