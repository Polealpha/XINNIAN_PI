$ErrorActionPreference = "Stop"

$repo = "E:\Desktop\lunwen\app windows"
$outLog = "E:\Desktop\lunwen\runtime_logs\desktop_electron_dev_run.log"
$errLog = "E:\Desktop\lunwen\runtime_logs\desktop_electron_dev_run.err.log"

$listener = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Get-Process electron -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

if (Test-Path $outLog) {
    Remove-Item $outLog -Force
}
if (Test-Path $errLog) {
    Remove-Item $errLog -Force
}

Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "cd /d ""$repo"" && npm run electron:dev") `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

Start-Sleep -Seconds 12
Get-Content -Path $outLog -Tail 80
