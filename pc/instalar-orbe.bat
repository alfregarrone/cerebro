@echo off
setlocal
cd /d "%~dp0"
title Instalar el orbe de Cerebro

echo ============================================
echo   Cerebro - orbe (la bola en pantalla)
echo ============================================
echo.
echo Cada vez que le hables a Alexa, aparece en esta pantalla una esfera que
echo escucha, piensa y habla. Sirve en la PC del agente y en cualquier otra.
echo.

where pythonw.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python en esta PC.
  echo Instalalo desde https://www.python.org/downloads/windows/
  echo IMPORTANTE: marca la casilla "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist "config_pc.json" (
  echo Esta PC no tiene el agente: hace falta el enlace con la skill ^(cerebro_link^).
  python orbe.py --configurar
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

echo Deteniendo una copia anterior, si la hay...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*orbe.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo Creando los accesos directos "Cerebro Orbe" (Inicio de Windows y Escritorio)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; foreach ($carpeta in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) { $lnk = $ws.CreateShortcut((Join-Path $carpeta 'Cerebro Orbe.lnk')); $lnk.TargetPath = (Get-Command pythonw.exe).Source; $lnk.Arguments = '\"' + (Join-Path $PWD 'orbe.py') + '\"'; $lnk.WorkingDirectory = $PWD.Path; $lnk.Description = 'Cerebro: la bola que escucha, piensa y habla'; if (Test-Path (Join-Path $PWD 'panel.ico')) { $lnk.IconLocation = (Join-Path $PWD 'panel.ico') + ',0' }; $lnk.Save() }"
if errorlevel 1 (
  echo [ERROR] No pude crear los accesos directos.
  pause
  exit /b 1
)

echo Iniciando el orbe (con una secuencia de prueba)...
start "" pythonw.exe "%CD%\orbe.py" --prueba

echo.
echo   LISTO. El orbe arranca solo con Windows. Esc o doble clic lo esconde; clic derecho lo cierra.
echo.
pause
