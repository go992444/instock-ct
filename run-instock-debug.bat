@echo off
chcp 65001 >nul
title Instock CT (Debug)
cd /d "%~dp0"
call "%~dp0run-instock.bat"
echo.
echo === run-instock.bat 종료 ===
pause
