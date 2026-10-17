# Actualiza Cerebro: copia los archivos nuevos a la carpeta donde ya esta instalado y lo reinicia.
# Se puede ejecutar desde cualquier carpeta (por ejemplo, donde descomprimiste el zip).
param([string]$Destino = "", [switch]$SinIniciar)
$ErrorActionPreference = 'Stop'
$origen = $PSScriptRoot

# 1) Donde esta instalado: lo dice el acceso directo de inicio de Windows; si no, el programa que esta corriendo
if (-not $Destino) {
  $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Cerebro PC.lnk'
  if (Test-Path $lnk) { $Destino = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).WorkingDirectory }
}
if (-not $Destino) {
  $p = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' } | Select-Object -First 1
  if ($p -and $p.CommandLine -match '"?([^"]*cerebro_pc\.py)') { $Destino = Split-Path $Matches[1] }
}
if (-not $Destino) { $Destino = Join-Path $env:USERPROFILE 'Cerebro' }
if (-not (Test-Path (Join-Path $Destino 'config_pc.json'))) {
  Write-Host "[ERROR] No encuentro tu Cerebro instalado en $Destino (falta config_pc.json)." -ForegroundColor Red
  exit 1
}
Write-Host "Cerebro esta instalado en: $Destino"

# 2) Copiar los archivos nuevos (nunca la configuracion ni las claves)
$mismo = (Resolve-Path $origen).Path.TrimEnd('\') -ieq (Resolve-Path $Destino).Path.TrimEnd('\')
if ($mismo) {
  Write-Host 'Ya estas en la carpeta de Cerebro: no hace falta copiar.'
} else {
  $protegidos = @('config_pc.json', 'gemini_key.txt', 'estado.json', 'latido.txt', 'panel_escritorio.json')
  $archivos = @(Get-ChildItem $origen -File | Where-Object { ($protegidos -notcontains $_.Name) -and (@('.py', '.bat', '.ps1', '.txt', '.html') -contains $_.Extension) })
  foreach ($a in $archivos) { Copy-Item $a.FullName -Destination $Destino -Force }
  Write-Host "Copie $($archivos.Count) archivos nuevos."
}
$version = ''
$linea = Select-String -Path (Join-Path $Destino 'cerebro_pc.py') -Pattern '^VERSION = "([^"]+)"' | Select-Object -First 1
if ($linea) { $version = $linea.Matches[0].Groups[1].Value }
if ($SinIniciar) { Write-Host "Version copiada: $version"; exit 0 }

# 3) Reiniciar Cerebro con los archivos nuevos
Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
$pyw = (Get-Command pythonw.exe).Source
Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $Destino 'cerebro_pc.py') + '"') -WorkingDirectory $Destino
Start-Sleep -Seconds 5
$corriendo = Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*cerebro_pc.py*' }
if ($corriendo) {
  Write-Host ''
  Write-Host "  LISTO: Cerebro version $version esta corriendo." -ForegroundColor Green
} else {
  Write-Host ''
  Write-Host '  ATENCION: no arranco. Revisa cerebro_pc.log en la carpeta de Cerebro.' -ForegroundColor Red
}
