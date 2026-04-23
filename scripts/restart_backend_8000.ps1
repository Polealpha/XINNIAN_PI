$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = "C:\Python314\python.exe"
$script = Join-Path $root "scripts\run_backend_8000.py"
$logs = Join-Path $root "runtime_logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stdoutLog = Join-Path $logs "backend_8000.log"
$stderrLog = Join-Path $logs "backend_8000.err.log"

$existing = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $existing) {
  if ($pid) {
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
  }
}

Start-Sleep -Milliseconds 500

Start-Process -FilePath $python `
  -ArgumentList $script `
  -WorkingDirectory $root `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -WindowStyle Hidden

Start-Sleep -Seconds 2
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess
