@echo off
setlocal
cd /d "%~dp0"
title Configurar Cerebro - agenda, mails y resumen

where python.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python. Instalalo desde python.org y marca "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Preparando el lector de calendarios...
python -m pip install --quiet --upgrade icalendar recurring-ical-events tzdata >nul 2>&1

python configurar.py

echo.
echo Reiniciando Cerebro...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
start "" pythonw.exe "%CD%\cerebro_pc.py"
timeout /t 4 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' }; if ($p) { Write-Host '  LISTO: Cerebro esta corriendo con la configuracion nueva.' -ForegroundColor Green } else { Write-Host '  ATENCION: no arranco. Revisa cerebro_pc.log en esta carpeta.' -ForegroundColor Red }"
echo.
pause
