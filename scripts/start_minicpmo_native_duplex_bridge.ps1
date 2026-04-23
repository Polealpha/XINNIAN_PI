$ErrorActionPreference = "Stop"

$repo = "E:\Desktop\lunwen"
$python = (Get-Command python.exe -ErrorAction Stop).Source
$log = "E:\Desktop\lunwen\runtime_logs\minicpmo_duplex_bridge.log"
$err = "E:\Desktop\lunwen\runtime_logs\minicpmo_duplex_bridge.err.log"

$listener = Get-NetTCPConnection -LocalPort 19002 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Remove-Item $log, $err -Force -ErrorAction SilentlyContinue

Start-Process -FilePath $python `
    -ArgumentList @('-u', '-m', 'deployment.minicpmo_native_duplex.bridge_app') `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err | Out-Null
