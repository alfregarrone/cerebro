@echo off
setlocal
cd /d "%~dp0"
title Instalar Cerebro PC

echo ============================================
echo   Cerebro PC - instalacion
echo ============================================
echo.

where pythonw.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python en esta PC.
  echo Instalalo desde https://www.python.org/downloads/windows/
  echo IMPORTANTE: marca la casilla "Add python.exe to PATH".
  echo Despues volve a ejecutar este instalador.
  echo.
  pause
  exit /b 1
)

if not exist "config_pc.json" (
  echo [ERROR] Falta el archivo config_pc.json en esta carpeta.
  pause
  exit /b 1
)

echo Deteniendo una copia anterior, si la hay...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo Creando el acceso directo de inicio de Windows...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Cerebro PC.lnk')); $lnk.TargetPath = (Get-Command pythonw.exe).Source; $lnk.Arguments = '\"' + (Join-Path $PWD 'cerebro_pc.py') + '\"'; $lnk.WorkingDirectory = $PWD.Path; $lnk.Description = 'Cerebro: puente entre Alexa y esta PC'; $lnk.Save()"
if errorlevel 1 (
  echo [ERROR] No pude crear el acceso directo de inicio.
  pause
  exit /b 1
)

echo Iniciando Cerebro...
start "" pythonw.exe "%CD%\cerebro_pc.py"

timeout /t 5 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' }; if ($p) { Write-Host '' ; Write-Host '  LISTO: Cerebro esta corriendo y arrancara solo con Windows.' -ForegroundColor Green } else { Write-Host '' ; Write-Host '  ATENCION: no arranco. Revisa cerebro_pc.log en esta carpeta.' -ForegroundColor Red }"

echo.
echo Tus notas se guardaran en: %USERPROFILE%\Cerebro
echo Para desinstalar, ejecuta desinstalar.bat
echo.
pause
