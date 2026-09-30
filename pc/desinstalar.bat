@echo off
setlocal
title Desinstalar Cerebro PC

echo Deteniendo Cerebro...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo Quitando el arranque automatico...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Join-Path ([Environment]::GetFolderPath('Startup')) 'Cerebro PC.lnk'; if (Test-Path $p) { Remove-Item $p -Force }"

echo.
echo Listo. Cerebro ya no corre en esta PC.
echo Tus notas siguen en %USERPROFILE%\Cerebro (no se borra nada).
echo.
pause
