param(
    [switch]$SkipNpmInstall,
    [switch]$SkipLfsPull
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $PathValue))
}

function Test-TextStartsWith([string]$PathValue, [string]$Prefix) {
    if (-not (Test-Path $PathValue)) {
        return $false
    }

    $content = Get-Content -Path $PathValue -TotalCount 1 -ErrorAction SilentlyContinue
    return [string]::IsNullOrEmpty($content) -eq $false -and $content.StartsWith($Prefix)
}

function Test-LfsRuntimeMissing([string]$RepoRoot) {
    $markers = @(
        "app windows\vendor\openclaw-runtime\openclaw.mjs",
        "app windows\vendor\python-runtime\python.exe",
        "app windows\vendor\python-site-packages\fastapi\__init__.py"
    )

    foreach ($marker in $markers) {
        $fullPath = Join-Path $RepoRoot $marker
        if (-not (Test-Path $fullPath)) {
            return $true
        }
        if (Test-TextStartsWith $fullPath "version https://git-lfs.github.com/spec/v1") {
            return $true
        }
    }

    return $false
}

function Ensure-GitLfs([string]$RepoRoot) {
    $git = Get-Command git -ErrorAction Stop
    try {
        & $git.Source lfs version | Out-Null
    } catch {
        throw "Git LFS is not installed. Please install Git LFS first, then rerun this script."
    }

    & $git.Source lfs install | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "git lfs install failed with exit code $LASTEXITCODE"
    }

    if ($SkipLfsPull) {
        return
    }

    if (Test-LfsRuntimeMissing $RepoRoot) {
        Write-Host "Pulling Git LFS runtime payloads..."
        Push-Location $RepoRoot
        try {
            & $git.Source lfs pull
        } finally {
            Pop-Location
        }
        if ($LASTEXITCODE -ne 0) {
            throw "git lfs pull failed with exit code $LASTEXITCODE"
        }
    } else {
        Write-Host "Git LFS runtime payloads already available."
    }
}

function Ensure-NpmInstall([string]$AppRoot) {
    if ($SkipNpmInstall) {
        return
    }

    $nodeModules = Join-Path $AppRoot "node_modules"
    $packageLock = Join-Path $AppRoot "package-lock.json"
    if (Test-Path $nodeModules) {
        Write-Host "Reusing existing npm dependencies at $nodeModules"
        return
    }

    $npm = Get-Command npm -ErrorAction Stop
    $command = if (Test-Path $packageLock) { "ci" } else { "install" }
    Write-Host "Installing desktop npm dependencies with npm $command ..."
    Push-Location $AppRoot
    try {
        & $npm.Source $command
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "npm $command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-CheckedPython([string]$RepoRoot, [string]$ScriptRelativePath, [string[]]$Arguments) {
    $python = Get-Command python -ErrorAction Stop
    $scriptPath = Join-Path $RepoRoot $ScriptRelativePath
    & $python.Source $scriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "python $ScriptRelativePath failed with exit code $LASTEXITCODE"
    }
}

function Invoke-CheckedPowerShellScript([string]$RepoRoot, [string]$ScriptRelativePath, [string[]]$Arguments) {
    $scriptPath = Join-Path $RepoRoot $ScriptRelativePath
    & powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $scriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ScriptRelativePath failed with exit code $LASTEXITCODE"
    }
}

$repoRoot = Resolve-FullPath (Join-Path $PSScriptRoot "..")
$appRoot = Join-Path $repoRoot "app windows"
$vendorRoot = Join-Path $appRoot "vendor"
$openClawRuntime = Join-Path $vendorRoot "openclaw-runtime"
$pythonRuntime = Join-Path $vendorRoot "python-runtime"
$pythonSitePackages = Join-Path $vendorRoot "python-site-packages"

Write-Host "Bootstrapping desktop runtime from $repoRoot"

Ensure-GitLfs $repoRoot
Ensure-NpmInstall $appRoot

Invoke-CheckedPython $repoRoot "scripts\prepare_desktop_python_runtime.py" @(
    "--target", $pythonSitePackages,
    "--python-home-target", $pythonRuntime,
    "--requirements", (Join-Path $repoRoot "backend\requirements.txt")
)

Invoke-CheckedPowerShellScript $repoRoot "scripts\prepare_desktop_openclaw_runtime.ps1" @(
    "-Source", (Join-Path $repoRoot "..\openclaw"),
    "-Target", $openClawRuntime
)

Write-Host ""
Write-Host "Desktop runtime bootstrap complete."
Write-Host "Ready to build from: $appRoot"
Write-Host "Suggested next step: npm run electron:dist"
