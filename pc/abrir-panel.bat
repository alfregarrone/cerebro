@echo off
setlocal
cd /d "%~dp0"
title Abrir el panel de Cerebro

where python.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python. Instalalo desde python.org y marca "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist "config_pc.json" (
  echo [ERROR] Falta config_pc.json en esta carpeta.
  pause
  exit /b 1
)

rem El token y el puerto real los deja el agente en estado.json (o el token en config_pc.json, si lo pusiste vos).
set "URL_TMP=%TEMP%\cerebro_panel_url.txt"
python -c "import json,pathlib as p,urllib.parse as u;c=json.loads(p.Path('config_pc.json').read_text(encoding='utf-8'));e=json.loads(p.Path('estado.json').read_text(encoding='utf-8')) if p.Path('estado.json').exists() else {};t=str(c.get('panel_token') or e.get('panel_token') or '');print('http://127.0.0.1:'+str(e.get('panel_puerto') or c.get('panel_puerto') or 8765)+'/?token='+u.quote(t,safe='') if t else '')" > "%URL_TMP%"
set "URL="
set /p URL=<"%URL_TMP%"
del "%URL_TMP%" >nul 2>&1

if "%URL%"=="" (
  echo El agente todavia no genero el token del panel.
  echo Arrancalo primero ^(instalar.bat^) y volve a probar en unos segundos.
  echo Si lo apagaste con "panel_activo": false en config_pc.json, volve a ponerlo en true.
  pause
  exit /b 1
)
echo Abriendo el panel en el navegador...
start "" "%URL%"
