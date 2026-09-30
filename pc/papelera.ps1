# Manda archivos o carpetas a la Papelera de reciclaje (recuperable), en vez de borrarlos para siempre.
# Uso:  powershell -ExecutionPolicy Bypass -File papelera.ps1 -Path "C:\ruta\archivo.txt"
param([Parameter(Mandatory = $true)][string[]]$Path)

Add-Type -AssemblyName Microsoft.VisualBasic

foreach ($p in $Path) {
    $item = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
    if (-not $item) { Write-Output "NO EXISTE: $p"; continue }
    $full = $item.Path
    try {
        if (Test-Path -LiteralPath $full -PathType Container) {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
                $full, 'OnlyErrorDialogs', 'SendToRecycleBin')
        } else {
            [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
                $full, 'OnlyErrorDialogs', 'SendToRecycleBin')
        }
        Write-Output "A LA PAPELERA: $full"
    } catch {
        Write-Output "ERROR con $full : $($_.Exception.Message)"
    }
}
