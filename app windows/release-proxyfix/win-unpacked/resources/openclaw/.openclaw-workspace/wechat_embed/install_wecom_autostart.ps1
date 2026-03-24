param(
  [string]$TaskName = "OpenClaw WeCom Bridge",
  [int]$DelaySeconds = 30,
  [ValidateSet("LIMITED", "HIGHEST")]
  [string]$RunLevel = "LIMITED"
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "start_wecom_with_openclaw.ps1"
if (-not (Test-Path $scriptPath)) {
  throw "missing script: $scriptPath"
}

$minutes = [int][math]::Floor($DelaySeconds / 60)
$seconds = [int]($DelaySeconds % 60)
$delay = "{0:D4}:{1:D2}" -f $minutes, $seconds
$taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$startupCmd = Join-Path $startupDir "OpenClaw-WeCom-Bridge.cmd"

$taskCreated = $false
$taskProc = Start-Process -FilePath "schtasks.exe" `
  -ArgumentList @(
    "/Create",
    "/TN", $TaskName,
    "/SC", "ONLOGON",
    "/DELAY", $delay,
    "/TR", $taskCmd,
    "/RL", $RunLevel,
    "/F"
  ) `
  -WindowStyle Hidden `
  -Wait `
  -PassThru
if ($taskProc.ExitCode -eq 0) {
  $taskCreated = $true
}

if ($taskCreated) {
  Write-Output "installed_mode=schtasks"
  Write-Output "installed_task=$TaskName"
  Write-Output "trigger=ONLOGON delay=$delay"
  Write-Output "run_level=$RunLevel"
  Write-Output "command=$taskCmd"
  return
}

if (-not (Test-Path $startupDir)) {
  New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
}

$cmdContent = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$scriptPath"
"@
Set-Content -Path $startupCmd -Value $cmdContent -Encoding ascii

Write-Output "installed_mode=startup-folder"
Write-Output "startup_file=$startupCmd"
Write-Output "command=$taskCmd"
