@echo off
setlocal
cd /d "%~dp0"
title Cerebro - pantalla, WhatsApp y casa

echo ==================================================
echo   Extras de Cerebro: pantalla, WhatsApp y casa
echo ==================================================
echo.

where python.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encontre Python. Instalalo desde python.org y marca "Add python.exe to PATH".
  pause
  exit /b 1
)

echo 1 de 3: control de pantalla y WhatsApp de escritorio...
python -m pip install --quiet --upgrade pyautogui pillow pyperclip pygetwindow
if errorlevel 1 goto error

echo 2 de 3: control de luces WiZ y enchufes TP-Link...
python -m pip install --quiet --upgrade python-kasa pywizlight
if errorlevel 1 goto error

echo 3 de 3: lector de Google Calendar...
python -m pip install --quiet --upgrade icalendar recurring-ical-events tzdata
if errorlevel 1 goto error

echo.
echo   LISTO. Ahora ejecuta configurar.bat (agenda, mails y resumen) y despues instalar.bat.
echo   (WhatsApp usa la aplicacion de escritorio que ya tenes logueada.)
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] Fallo la instalacion. Revisa tu conexion e intenta de nuevo.
pause
exit /b 1
