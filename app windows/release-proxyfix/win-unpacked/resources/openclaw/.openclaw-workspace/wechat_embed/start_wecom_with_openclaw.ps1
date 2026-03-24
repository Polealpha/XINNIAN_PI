param(
  [int]$OpenClawPort = 18789,
  [int]$WeComPort = 28789,
  [int]$WaitOpenClawSec = 90
)

$ErrorActionPreference = "Stop"

$workspaceRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $workspaceRoot ".venv39\Scripts\python.exe"
$cloudflaredExe = Join-Path $workspaceRoot "tools\cloudflared.exe"

$wecomOut = Join-Path $workspaceRoot "logs\wecom_gateway_autostart.out.log"
$wecomErr = Join-Path $workspaceRoot "logs\wecom_gateway_autostart.err.log"
$cfOut = Join-Path $workspaceRoot "logs\cloudflared_autostart.out.log"
$cfErr = Join-Path $workspaceRoot "logs\cloudflared_autostart.err.log"

function Ensure-File {
  param([string]$Path)
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  if (-not (Test-Path $Path)) {
    New-Item -ItemType File -Path $Path | Out-Null
  }
}

function Test-HttpOk {
  param([string]$Url, [int]$TimeoutSec = 2)
  try {
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
    return ($resp.StatusCode -eq 200)
  } catch {
    return $false
  }
}

function Has-ProcessLike {
  param([string]$Name, [string]$Pattern)
  $proc = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq $Name -and $_.CommandLine -match $Pattern
  } | Select-Object -First 1
  return ($null -ne $proc)
}

for ($i = 0; $i -lt $WaitOpenClawSec; $i++) {
  if (Test-HttpOk -Url "http://127.0.0.1:$OpenClawPort/healthz" -TimeoutSec 2) {
    break
  }
  Start-Sleep -Seconds 1
}

Ensure-File -Path $wecomOut
Ensure-File -Path $wecomErr
Ensure-File -Path $cfOut
Ensure-File -Path $cfErr

if (-not (Test-Path $pythonExe)) {
  throw "python not found: $pythonExe"
}

$wecomPattern = "wecom_gateway\.py.*--port\s+`"?$WeComPort`"?"
if (-not (Has-ProcessLike -Name "python.exe" -Pattern $wecomPattern)) {
  Start-Process -FilePath $pythonExe `
    -ArgumentList @(
      "-u",
      "wechat_embed\wecom_gateway.py",
      "--env-file",
      "wechat_embed\.env.wecom",
      "run",
      "--host",
      "0.0.0.0",
      "--port",
      "$WeComPort"
    ) `
    -WorkingDirectory $workspaceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $wecomOut `
    -RedirectStandardError $wecomErr | Out-Null
}

if (-not (Test-Path $cloudflaredExe)) {
  throw "cloudflared not found: $cloudflaredExe"
}

$cfPattern = "cloudflared\.exe.*--url\s+http://127\.0\.0\.1:$WeComPort"
if (-not (Has-ProcessLike -Name "cloudflared.exe" -Pattern $cfPattern)) {
  Start-Process -FilePath $cloudflaredExe `
    -ArgumentList @(
      "tunnel",
      "--url",
      "http://127.0.0.1:$WeComPort",
      "--no-autoupdate"
    ) `
    -WorkingDirectory $workspaceRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $cfOut `
    -RedirectStandardError $cfErr | Out-Null
}

