# Descarga UP-Fall con omnifall y reintenta mientras Google Drive devuelva "Quota exceeded".
# omnifall reanuda donde lo dejo, asi que cada intento continua el anterior.
#
# Uso (en segundo plano, sin ventana):
#   Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','ml\datasets\download_up_fall.ps1' -WindowStyle Hidden
# Estado:  Get-Content <root>\up_fall_status.txt
# Parar:   Stop-Process -Id (Get-Content <root>\retry_up_fall.pid)
#
# <root> es $env:RESIDENCIA_DATA_DIR\omnifall, o C:\data\residencia\omnifall por defecto.
# (Sin acentos a proposito: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.)

$dataDir = if ($env:RESIDENCIA_DATA_DIR) { $env:RESIDENCIA_DATA_DIR } else { 'C:\data\residencia' }
$root = Join-Path $dataDir 'omnifall'
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
$maxAttempts = 8
$waitSeconds = 3 * 3600

$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:PYTHONUNBUFFERED = '1'
New-Item -ItemType Directory -Force (Join-Path $root 'up_fall\video') | Out-Null
New-Item -ItemType Directory -Force (Join-Path $root 'logs') | Out-Null
$PID | Set-Content (Join-Path $root 'retry_up_fall.pid')
$status = Join-Path $root 'up_fall_status.txt'

for ($i = 1; $i -le $maxAttempts; $i++) {
    $log = Join-Path $root ("logs\up_fall_attempt_{0:D2}.log" -f $i)
    "intento $i de $maxAttempts empezado $(Get-Date -Format s)" | Set-Content $status
    # omnifall 0.2.0 usa 'requests' sin declararlo como dependencia.
    cmd /c "`"$uv`" run -q --no-project --with omnifall --with requests omnifall prepare up_fall --yes --video-dir `"$root\up_fall\video`" --download-dir `"$root\downloads`" > `"$log`" 2>&1"
    if ($LASTEXITCODE -eq 0) {
        "COMPLETADO en el intento $i, $(Get-Date -Format s)" | Set-Content $status
        exit 0
    }
    $next = (Get-Date).AddSeconds($waitSeconds)
    "intento $i fallo $(Get-Date -Format s); siguiente intento hacia $($next.ToString('s')) (ver $log)" | Set-Content $status
    if ($i -lt $maxAttempts) { Start-Sleep -Seconds $waitSeconds }
}
"AGOTADOS los $maxAttempts intentos $(Get-Date -Format s); revisar logs" | Set-Content $status
exit 1
