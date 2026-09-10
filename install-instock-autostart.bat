@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "TASK=Instock CT Auto Start"
set "SCRIPT=%~dp0_run-instock-core.bat"

echo Registering Windows Task Scheduler job: %TASK%
echo Runs on login, starts Instock CT in the background.
echo.

schtasks /Delete /TN "%TASK%" /F >nul 2>&1
schtasks /Create /TN "%TASK%" /SC ONLOGON /RL LIMITED /F /TR "cmd /c \"\"%SCRIPT%\"\"" >nul
if errorlevel 1 (
  echo ERROR: Could not create scheduled task.
  echo Try right-click this file -^> Run as administrator.
  pause
  exit /b 1
)

echo Done.
echo - After reboot/login, open http://localhost:8501
echo - Or double-click open-instock.bat anytime
echo - To remove: schtasks /Delete /TN "%TASK%" /F
echo.
pause
