param(
    [Parameter(Mandatory = $true)]
    [string]$Setup,
    [Parameter(Mandatory = $true)]
    [string]$ProbeDir,
    [int]$TimeoutMinutes = 15
)

$ErrorActionPreference = "Stop"

Get-Process | Where-Object { $_.ProcessName -like 'EmoResonance Setup*' -or $_.ProcessName -like 'EmoResonance*' } | Stop-Process -Force -ErrorAction SilentlyContinue

if (Test-Path $ProbeDir) {
    & cmd /c "rmdir /s /q `"$ProbeDir`""
}

$process = Start-Process -FilePath $Setup -ArgumentList '/S',("/D=" + $ProbeDir) -PassThru
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$expected = @(
    (Join-Path $ProbeDir 'EmoResonance.exe'),
    (Join-Path $ProbeDir 'resources\app.asar'),
    (Join-Path $ProbeDir 'resources\bridge-runtime'),
    (Join-Path $ProbeDir 'resources\openclaw')
)

while ((Get-Date) -lt $deadline) {
    $process.Refresh()
    $missing = @($expected | Where-Object { -not (Test-Path $_) })
    if ($missing.Count -eq 0 -or $process.HasExited) {
        break
    }
    Start-Sleep -Seconds 10
}

$process.Refresh()
$missing = @($expected | Where-Object { -not (Test-Path $_) })
[PSCustomObject]@{
    MissingCount = $missing.Count
    Missing = ($missing -join '; ')
    HasExited = $process.HasExited
    ExitCode = $(if ($process.HasExited) { $process.ExitCode } else { -999 })
    ProbeFiles = $(if (Test-Path $ProbeDir) { (Get-ChildItem -Path $ProbeDir -Force | Select-Object -ExpandProperty Name) -join ', ' } else { '' })
} | ConvertTo-Json -Compress
