$ErrorActionPreference = "Stop"

$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $appRoot
$nodeRoot = "D:\tools\node-v24.14.1-win-x64"
$gitCmd = Join-Path $env:LOCALAPPDATA "GitHubDesktop\app-3.5.7\resources\app\git\cmd"
$pythonExe = Join-Path $appRoot "vendor\python-runtime\python.exe"
$pythonSitePackages = Join-Path $appRoot "vendor\python-site-packages"
$electronExe = Join-Path $appRoot "node_modules\electron\dist\electron.exe"

if (-not (Test-Path $electronExe)) {
    throw "Missing Electron executable: $electronExe"
}

$pathParts = @($nodeRoot, $gitCmd, $env:PATH) | Where-Object { $_ -and $_.Trim() }
$env:PATH = [string]::Join(";", $pathParts)
$env:EMOTION_BRIDGE_PYTHON = $pythonExe
$pythonPathParts = @($repoRoot, $pythonSitePackages, $env:PYTHONPATH) | Where-Object { $_ -and $_.Trim() }
$env:PYTHONPATH = [string]::Join(";", $pythonPathParts)

$runningElectron = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq "electron.exe" -and $_.ExecutablePath -eq $electronExe
}

foreach ($proc in $runningElectron) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Failed to stop existing Electron process $($proc.ProcessId): $($_.Exception.Message)"
    }
}

if ($runningElectron) {
    Start-Sleep -Milliseconds 800
}

Start-Process -FilePath $electronExe -ArgumentList "electron/main.cjs" -WorkingDirectory $appRoot
