param(
  [int]$Port = 18789,
  [string]$Session = "agent:main:main",
  [switch]$SkipBuild,
  [switch]$Foreground,
  [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

function Stop-PortListeners {
  param([int]$TargetPort)

  $netstatLines = netstat -ano -p tcp | Select-String ":$TargetPort"
  $pids = @()
  foreach ($line in $netstatLines) {
    $parts = ($line.ToString() -replace "\s+", " ").Trim().Split(" ")
    if ($parts.Length -lt 5) {
      continue
    }
    $state = $parts[3]
    $procId = $parts[4]
    if ($state -ne "LISTENING") {
      continue
    }
    if ($procId -match "^\d+$" -and $procId -ne "0") {
      $pids += [int]$procId
    }
  }

  foreach ($listenerPid in ($pids | Sort-Object -Unique)) {
    try {
      Stop-Process -Id $listenerPid -Force -ErrorAction Stop
      Write-Host "Stopped PID $listenerPid on port $TargetPort"
    } catch {
      Write-Warning "Failed to stop PID ${listenerPid}: $($_.Exception.Message)"
    }
  }
}

function Stop-GatewayProcesses {
  param([int]$TargetPort)

  $gatewayProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "node.exe" -and
    $_.CommandLine -match "openclaw\.mjs.*gateway run" -and
    $_.CommandLine -match "--port\s+`"?$TargetPort`"?"
  }

  foreach ($proc in $gatewayProcs) {
    try {
      taskkill /PID $proc.ProcessId /T /F | Out-Null
      Write-Host "Stopped gateway process tree PID $($proc.ProcessId)"
    } catch {
      Write-Warning "Failed to stop gateway PID $($proc.ProcessId): $($_.Exception.Message)"
    }
  }
}

$shouldOpenBrowser = $OpenBrowser.IsPresent

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Stop-GatewayProcesses -TargetPort $Port
Stop-PortListeners -TargetPort $Port

if (-not $SkipBuild) {
  Write-Host "Building dist from current source..."
  pnpm exec tsdown --no-clean
}

if ($Foreground) {
  Write-Host "Starting gateway in foreground on ws://127.0.0.1:$Port ..."
  pnpm openclaw gateway run --bind loopback --port $Port --force
  exit $LASTEXITCODE
}

$logDir = Join-Path $env:LOCALAPPDATA "Temp\openclaw"
$outLog = Join-Path $logDir "gateway-manual.out.log"
$errLog = Join-Path $logDir "gateway-manual.err.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$cmd = "Set-Location '$repoRoot'; pnpm openclaw gateway run --bind loopback --port $Port --force"
$proc = Start-Process -FilePath "powershell" `
  -ArgumentList @("-NoLogo", "-NoProfile", "-Command", $cmd) `
  -PassThru `
  -WindowStyle Hidden `
  -RedirectStandardOutput $outLog `
  -RedirectStandardError $errLog

for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  $isListening = (netstat -ano | Select-String "127.0.0.1:$Port\s+.*LISTENING\s+\d+")
  if ($isListening) {
    break
  }
}

$line = netstat -ano | Select-String "127.0.0.1:$Port\s+.*LISTENING\s+(\d+)" | Select-Object -First 1
if (-not $line) {
  throw "Gateway did not start on port $Port. Check $outLog and $errLog"
}

Write-Host "Gateway started (launcher PID $($proc.Id)) on ws://127.0.0.1:$Port"
Write-Host "Logs:"
Write-Host "  $outLog"
Write-Host "  $errLog"

if ($shouldOpenBrowser) {
  $sessionEncoded = [System.Uri]::EscapeDataString($Session)
  $url = "http://127.0.0.1:$Port/chat?session=$sessionEncoded"
  try {
    $token = (pnpm -s openclaw config get gateway.auth.token 2>$null | Select-Object -Last 1).Trim()
    if ($token) {
      $tokenEncoded = [System.Uri]::EscapeDataString($token)
      $url = "$url&token=$tokenEncoded"
    }
  } catch {
    # Keep URL without token if config lookup fails.
  }
  Start-Process $url | Out-Null
  Write-Host "Opened: $url"
}
