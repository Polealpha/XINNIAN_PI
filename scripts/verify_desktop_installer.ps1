param(
  [string]$ReleaseDir = ".\release",
  [int]$TimeoutMinutes = 15
)

$ErrorActionPreference = "Stop"

$resolvedReleaseDir = Resolve-Path $ReleaseDir
$setup = Get-ChildItem -Path $resolvedReleaseDir -Filter "*Setup*.exe" | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if (-not $setup) {
  throw "Setup.exe not found in $resolvedReleaseDir"
}

# Old NSIS processes can keep the temp extraction dir locked and make a fresh
# silent install fail immediately with exit code 2.
Get-Process | Where-Object { $_.ProcessName -like "EmoResonance Setup*" } | Stop-Process -Force -ErrorAction SilentlyContinue

$probeRoot = Join-Path $env:SystemDrive ("emo-probe-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 12))
New-Item -ItemType Directory -Path $probeRoot | Out-Null

try {
  $process = Start-Process -FilePath $setup.FullName -ArgumentList "/S","/D=$probeRoot" -PassThru

  $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
      break
    }
    Start-Sleep -Seconds 5
    $process.Refresh()
  }

  if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "Silent installer did not finish within ${TimeoutMinutes} minutes"
  }

  if ($process.ExitCode -ne 0) {
    throw "Silent installer exited with code $($process.ExitCode)"
  }

  $expected = @(
    (Join-Path $probeRoot "EmoResonance.exe"),
    (Join-Path $probeRoot "resources\app.asar"),
    (Join-Path $probeRoot "resources\bridge-runtime"),
    (Join-Path $probeRoot "resources\openclaw"),
    (Join-Path $probeRoot "resources\openclaw\dist\entry.js"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\chalk\package.json"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\tslog\package.json"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\@anthropic-ai\sdk\package.json"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\@aws-sdk\client-bedrock-runtime\package.json"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\@google\genai\package.json"),
    (Join-Path $probeRoot "resources\openclaw\node_modules\openai\package.json")
  )

  $missing = @($expected | Where-Object { -not (Test-Path $_) })
  if ($missing.Count -gt 0) {
    throw "Installer verification failed; missing: $($missing -join ', ')"
  }

  $openclawCli = Join-Path $probeRoot "resources\openclaw\openclaw.mjs"
  $openclawProcess = Start-Process -FilePath "node" -ArgumentList "`"$openclawCli`"","--help" -WorkingDirectory (Split-Path -Parent $openclawCli) -PassThru -RedirectStandardOutput (Join-Path $probeRoot "openclaw-help.out") -RedirectStandardError (Join-Path $probeRoot "openclaw-help.err")
  try {
    Wait-Process -Id $openclawProcess.Id -Timeout 30 -ErrorAction Stop
    $openclawProcess.Refresh()
    $stdout = ""
    $stderr = ""
    $stdoutPath = Join-Path $probeRoot "openclaw-help.out"
    $stderrPath = Join-Path $probeRoot "openclaw-help.err"
    if (Test-Path $stdoutPath) {
      $stdout = Get-Content $stdoutPath -Raw
    }
    if (Test-Path $stderrPath) {
      $stderr = Get-Content $stderrPath -Raw
    }
    $stdoutLooksHealthy = $stdout -match "Usage:\s+openclaw" -and $stdout -match "Commands:"
    if (($openclawProcess.ExitCode -ne 0) -and (-not $stdoutLooksHealthy)) {
      throw "OpenClaw runtime verification failed with exit code $($openclawProcess.ExitCode). Probe root: $probeRoot`nSTDOUT:`n$stdout`nSTDERR:`n$stderr"
    }
  } catch {
    Stop-Process -Id $openclawProcess.Id -Force -ErrorAction SilentlyContinue
    throw
  }
  Write-Host "Installer verification passed for $($setup.FullName)"
} finally {
  if ($? -and (Test-Path $probeRoot)) {
    Remove-Item -Path $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}
