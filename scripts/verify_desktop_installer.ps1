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

$probeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("emoresonance-install-probe-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $probeRoot | Out-Null

try {
  $process = Start-Process -FilePath $setup.FullName -ArgumentList "/S","/D=$probeRoot" -PassThru

  $expected = @(
    (Join-Path $probeRoot "EmoResonance.exe"),
    (Join-Path $probeRoot "resources\app.asar"),
    (Join-Path $probeRoot "resources\bridge-runtime"),
    (Join-Path $probeRoot "resources\openclaw")
  )

  $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
  while ((Get-Date) -lt $deadline) {
    $missing = @($expected | Where-Object { -not (Test-Path $_) })
    if ($missing.Count -eq 0) {
      break
    }
    Start-Sleep -Seconds 5
  }

  $missing = @($expected | Where-Object { -not (Test-Path $_) })
  if ($missing.Count -gt 0) {
    throw "Installer verification failed; missing: $($missing -join ', ')"
  }

  try {
    if (-not $process.HasExited) {
      Wait-Process -Id $process.Id -Timeout 60 -ErrorAction Stop
    }
    $process.Refresh()
    if ($process.HasExited -and $process.ExitCode -ne 0) {
      throw "Silent installer exited with code $($process.ExitCode)"
    }
  } catch {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
  }

  Write-Host "Installer verification passed for $($setup.FullName)"
} finally {
  if (Test-Path $probeRoot) {
    Remove-Item -Path $probeRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}
