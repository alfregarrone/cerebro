@echo off
setlocal
cd /d "%~dp0"
title Instalar el panel de escritorio de Cerebro

echo ============================================
echo   Cerebro - panel de escritorio
echo ============================================
echo.
echo Esto se instala en TU PC principal: abre en una ventana el panel del
echo agente que corre en la otra PC. (El agente NO se instala aca.)
echo.

where pythonw.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python en esta PC.
  echo Instalalo desde https://www.python.org/downloads/windows/
  echo IMPORTANTE: marca la casilla "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Instalando la ventana nativa (pywebview). Si falla, se usa Edge en modo aplicacion.
python -m pip install --quiet --upgrade pywebview >nul 2>&1

echo.
echo Configurando la conexion con la otra PC...
python panel_escritorio.py --configurar
if errorlevel 1 (
  echo.
  echo No quedo configurado. Volve a ejecutar este instalador cuando tengas la direccion y el token.
  pause
  exit /b 1
)

echo Creando los accesos directos "Cerebro Panel" (Escritorio y menu Inicio)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; foreach ($carpeta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { $lnk = $ws.CreateShortcut((Join-Path $carpeta 'Cerebro Panel.lnk')); $lnk.TargetPath = (Get-Command pythonw.exe).Source; $lnk.Arguments = '\"' + (Join-Path $PWD 'panel_escritorio.py') + '\"'; $lnk.WorkingDirectory = $PWD.Path; $lnk.Description = 'Cerebro: panel del agente de la otra PC'; if (Test-Path (Join-Path $PWD 'panel.ico')) { $lnk.IconLocation = (Join-Path $PWD 'panel.ico') + ',0' }; $lnk.Save() }"
if errorlevel 1 (
  echo [ERROR] No pude crear los accesos directos.
  pause
  exit /b 1
)

echo.
echo   LISTO. Abri "Cerebro Panel" desde el Escritorio o el menu Inicio.
echo   Para cambiar la direccion o el token:  python panel_escritorio.py --configurar
echo.
start "" pythonw.exe "%CD%\panel_escritorio.py"
pause
