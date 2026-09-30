@echo off
setlocal
title Instalar Claude Code para Cerebro

echo ============================================
echo   Claude Code - para las tareas largas
echo ============================================
echo.

where node >nul 2>&1
if errorlevel 1 goto sin_node
where npm >nul 2>&1
if errorlevel 1 goto sin_node

for /f "tokens=*" %%v in ('node --version') do set NODEV=%%v
echo Node.js detectado: %NODEV%
echo.

if defined SOLO_CHEQUEO (
  echo [modo chequeo] No instalo nada.
  goto fin
)

echo Instalando Claude Code (puede tardar unos minutos)...
call npm install -g @anthropic-ai/claude-code
if errorlevel 1 (
  echo.
  echo [ERROR] La instalacion fallo. Revisa tu conexion e intenta de nuevo.
  pause
  exit /b 1
)

echo.
where claude >nul 2>&1
if errorlevel 1 (
  echo [ATENCION] Se instalo pero no aparece el comando "claude".
  echo Cierra esta ventana, abre una nueva y escribi: claude
) else (
  echo   LISTO: Claude Code instalado.
)

echo.
echo ULTIMO PASO, lo haces vos:
echo   1. Abri una terminal nueva (tecla Windows, escribi cmd, Enter).
echo   2. Escribi:  claude
echo   3. Adentro escribi:  /login   y entra con tu cuenta de Claude.
echo   4. Cerra la terminal. Cerebro ya puede hacer tareas largas.
echo.
goto fin

:sin_node
echo [ERROR] Falta Node.js, que es necesario para Claude Code.
echo.
echo Instalalo asi:
echo   Opcion A: descarga la version LTS desde https://nodejs.org
echo   Opcion B: abri PowerShell y escribi:  winget install OpenJS.NodeJS.LTS
echo.
echo Despues cerra esta ventana, abri una nueva y volve a ejecutar este archivo.
echo.

:fin
pause
