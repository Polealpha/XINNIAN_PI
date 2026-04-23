$ErrorActionPreference = "Stop"

$repo = "E:\Desktop\lunwen"
$python = "C:\Python314\python.exe"
$log = "E:\Desktop\lunwen\runtime_logs\backend_8012.log"
$errLog = "E:\Desktop\lunwen\runtime_logs\backend_8012.err.log"

$listener = Get-NetTCPConnection -LocalPort 8012 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
if (Test-Path $log) {
    Remove-Item $log -Force
}
if (Test-Path $errLog) {
    Remove-Item $errLog -Force
}

Start-Process -FilePath $python `
    -ArgumentList @('E:\Desktop\lunwen\scripts\run_backend_8012.py') `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $log `
    -RedirectStandardError $errLog | Out-Null
