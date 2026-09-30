@echo off
setlocal
cd /d "%~dp0"
title Actualizar Cerebro
echo ============================================
echo   Actualizar Cerebro
echo ============================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0actualizar.ps1"
echo.
pause
