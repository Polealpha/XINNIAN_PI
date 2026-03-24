param(
  [string]$TaskName = "OpenClaw WeCom Bridge"
)

$ErrorActionPreference = "Stop"

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$startupCmd = Join-Path $startupDir "OpenClaw-WeCom-Bridge.cmd"

$taskProc = Start-Process -FilePath "schtasks.exe" `
  -ArgumentList @("/Delete", "/TN", $TaskName, "/F") `
  -WindowStyle Hidden `
  -Wait `
  -PassThru
if ($taskProc.ExitCode -eq 0) {
  Write-Output "removed_task=$TaskName"
}

if (Test-Path $startupCmd) {
  Remove-Item -Path $startupCmd -Force
  Write-Output "removed_startup_file=$startupCmd"
}
