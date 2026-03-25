param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [string]$Target
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }

    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $PathValue))
}

function Invoke-CmdChecked([string]$CommandLine) {
    & cmd.exe /c $CommandLine
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
    }
}

function Prune-OpenClawRuntime([string]$RuntimeRoot) {
    $pnpmRoot = Join-Path $RuntimeRoot "node_modules\.pnpm"
    if (-not (Test-Path $pnpmRoot)) {
        return
    }

    $patterns = @(
        "@node-llama-cpp*",
        "node-llama-cpp@*",
        "@napi-rs+canvas*"
    )

    foreach ($pattern in $patterns) {
        Get-ChildItem $pnpmRoot -Directory -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
            Invoke-CmdChecked "rmdir /s /q `"$($_.FullName)`""
        }
    }

    $topLevelRemovals = @(
        (Join-Path $RuntimeRoot "node_modules\node-llama-cpp"),
        (Join-Path $RuntimeRoot "node_modules\@napi-rs"),
        (Join-Path $RuntimeRoot "node_modules\.pnpm\node_modules\@node-llama-cpp"),
        (Join-Path $RuntimeRoot "node_modules\.pnpm\node_modules\@napi-rs"),
        (Join-Path $RuntimeRoot "node_modules\.pnpm\pdfjs-dist@5.4.624\node_modules\@napi-rs")
    )

    foreach ($path in $topLevelRemovals) {
        if (Test-Path $path) {
            Invoke-CmdChecked "rmdir /s /q `"$path`""
        }
    }
}

$sourcePath = Resolve-FullPath $Source
$targetPath = Resolve-FullPath $Target

if (-not (Test-Path $sourcePath)) {
    throw "OpenClaw source path does not exist: $sourcePath"
}

$pnpm = Get-Command pnpm -ErrorAction Stop
$targetParent = Split-Path -Parent $targetPath

if ($targetParent -and -not (Test-Path $targetParent)) {
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
}

if (Test-Path $targetPath) {
    $staleName = "{0}-stale-{1}" -f (Split-Path -Leaf $targetPath), (Get-Date -Format "yyyyMMddHHmmss")
    $stalePath = Join-Path $targetParent $staleName
    Move-Item -Force $targetPath $stalePath
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "rmdir /s /q `"$stalePath`"" -WindowStyle Hidden | Out-Null
}

Write-Host "Preparing OpenClaw runtime from $sourcePath to $targetPath"

& $pnpm.Source --dir $sourcePath --filter openclaw deploy --legacy --prod --offline $targetPath

if ($LASTEXITCODE -ne 0) {
    throw "pnpm deploy failed with exit code $LASTEXITCODE"
}

Prune-OpenClawRuntime $targetPath
