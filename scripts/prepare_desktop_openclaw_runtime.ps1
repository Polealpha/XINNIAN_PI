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

function Test-OpenClawRuntimeReady([string]$RuntimeRoot) {
    $required = @(
        (Join-Path $RuntimeRoot "openclaw.mjs"),
        (Join-Path $RuntimeRoot "package.json"),
        (Join-Path $RuntimeRoot "dist\entry.js"),
        (Join-Path $RuntimeRoot "dist\index.js"),
        (Join-Path $RuntimeRoot "node_modules"),
        (Join-Path $RuntimeRoot "node_modules\yaml\dist\doc\directives.js"),
        (Join-Path $RuntimeRoot "node_modules\chalk\package.json"),
        (Join-Path $RuntimeRoot "node_modules\tslog\package.json"),
        (Join-Path $RuntimeRoot "node_modules\@anthropic-ai\sdk\package.json"),
        (Join-Path $RuntimeRoot "node_modules\@aws-sdk\client-bedrock-runtime\package.json"),
        (Join-Path $RuntimeRoot "node_modules\@google\genai\package.json"),
        (Join-Path $RuntimeRoot "node_modules\openai\package.json"),
        (Join-Path $RuntimeRoot "skills"),
        (Join-Path $RuntimeRoot "extensions")
    )

    return @($required | Where-Object { -not (Test-Path $_) }).Count -eq 0
}

function Invoke-CmdChecked([string]$CommandLine) {
    & cmd.exe /c $CommandLine
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
    }
}

function Copy-Tree([string]$SourceDir, [string]$TargetDir) {
    if (-not (Test-Path $SourceDir)) {
        throw "Missing source directory: $SourceDir"
    }

    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    & robocopy.exe $SourceDir $TargetDir /MIR /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code $LASTEXITCODE from $SourceDir to $TargetDir"
    }
}

function Copy-MaterializedRuntime([string]$SourceDir, [string]$TargetDir) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    & robocopy.exe $SourceDir $TargetDir /MIR /R:1 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        $required = @(
            (Join-Path $TargetDir "openclaw.mjs"),
            (Join-Path $TargetDir "node_modules\yaml\dist\doc\directives.js"),
            (Join-Path $TargetDir "node_modules\chalk\package.json")
        )
        $missing = @($required | Where-Object { -not (Test-Path $_) })
        if ($missing.Count -gt 0) {
            throw "robocopy materialization failed with exit code $LASTEXITCODE. Missing: $($missing -join ', ')"
        }
        Write-Warning "robocopy returned exit $LASTEXITCODE while materializing OpenClaw runtime, but required files are present. Continuing."
    }
}

function Copy-DirectoryContents([string]$SourceDir, [string]$TargetDir) {
    if (-not (Test-Path $SourceDir)) {
        throw "Missing source directory: $SourceDir"
    }

    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    Get-ChildItem $SourceDir -Force | ForEach-Object {
        $destination = Join-Path $TargetDir $_.Name
        if ($_.PSIsContainer) {
            Copy-Tree $_.FullName $destination
        } else {
            Copy-Item -Force $_.FullName $destination
        }
    }
}

function Materialize-HoistedNodeModules([string]$RuntimeRoot) {
    $sourceHoisted = Join-Path $RuntimeRoot "node_modules\.pnpm\node_modules"
    $targetNodeModules = Join-Path $RuntimeRoot "node_modules"
    if (-not (Test-Path $sourceHoisted)) {
        return
    }

    Get-ChildItem $sourceHoisted -Force | ForEach-Object {
        if ($_.Name -eq ".bin") {
            return
        }

        $targetPath = Join-Path $targetNodeModules $_.Name
        if (-not (Test-Path $targetPath)) {
            Copy-Tree $_.FullName $targetPath
            return
        }

        if ($_.PSIsContainer -and $_.Name.StartsWith("@")) {
            Get-ChildItem $_.FullName -Force | ForEach-Object {
                $scopedTarget = Join-Path $targetPath $_.Name
                if (-not (Test-Path $scopedTarget)) {
                    Copy-Tree $_.FullName $scopedTarget
                }
            }
        }
    }
}

function Initialize-ProxyEnvironment() {
    if ($env:HTTPS_PROXY -or $env:HTTP_PROXY) {
        return
    }

    try {
        $listening = Test-NetConnection -ComputerName 127.0.0.1 -Port 7897 -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($listening) {
            $proxy = "http://127.0.0.1:7897"
            $env:HTTPS_PROXY = $proxy
            $env:HTTP_PROXY = $proxy
            $env:ALL_PROXY = $proxy
            Write-Host "Using local proxy $proxy for OpenClaw runtime preparation"
        }
    } catch {
        # Proxy detection is best-effort only.
    }
}

function Prune-OpenClawRuntime([string]$RuntimeRoot) {
    $pnpmRoot = Join-Path $RuntimeRoot "node_modules\.pnpm"
    if (-not (Test-Path $pnpmRoot)) {
        return
    }

    Get-ChildItem $pnpmRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "@node-llama-cpp*" -or $_.Name -like "node-llama-cpp@*" -or $_.Name -like "@napi-rs+canvas*" } |
        ForEach-Object {
            Invoke-CmdChecked "rmdir /s /q `"$($_.FullName)`""
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

    Get-ChildItem $RuntimeRoot -Recurse -File -Include *.d.ts,*.d.cts,*.d.mts,*.map -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-Item -Force $_.FullName -ErrorAction SilentlyContinue
        }

    Get-ChildItem -Path $RuntimeRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("docs", "examples", "example", "test", "tests") } |
        Sort-Object FullName -Descending |
        ForEach-Object {
            Invoke-CmdChecked "rmdir /s /q `"$($_.FullName)`""
        }

    foreach ($typescriptPath in @(
        (Join-Path $RuntimeRoot "node_modules\typescript"),
        (Join-Path $RuntimeRoot "node_modules\.pnpm\typescript@5.9.3")
    )) {
        if (Test-Path $typescriptPath) {
            Invoke-CmdChecked "rmdir /s /q `"$typescriptPath`""
        }
    }
}

function Materialize-OpenClawRuntime([string]$RuntimeRoot) {
    $materializedRoot = "{0}-materialized-{1}" -f $RuntimeRoot, ([System.Guid]::NewGuid().ToString("N"))
    Copy-MaterializedRuntime -SourceDir $RuntimeRoot -TargetDir $materializedRoot

    $staleRoot = "{0}-stale-{1}" -f $RuntimeRoot, (Get-Date -Format "yyyyMMddHHmmss")
    if (Test-Path $staleRoot) {
        Invoke-CmdChecked "rmdir /s /q `"$staleRoot`""
    }

    Move-Item -Force $RuntimeRoot $staleRoot
    Move-Item -Force $materializedRoot $RuntimeRoot
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "rmdir /s /q `"$staleRoot`"" -WindowStyle Hidden | Out-Null
}

function Get-OpenClawRuntimeVersion([string]$SourceDir, [string]$TargetDir) {
    foreach ($candidate in @(
        (Join-Path $SourceDir "package.json"),
        (Join-Path $TargetDir "package.json"),
        (Join-Path $PSScriptRoot "..\app windows\vendor\openclaw-runtime\package.json")
    )) {
        if (Test-Path $candidate) {
            try {
                $pkg = Get-Content $candidate -Raw | ConvertFrom-Json
                if ($pkg.version) {
                    return [string]$pkg.version
                }
            } catch {
                # Ignore parse errors and try the next source.
            }
        }
    }
    return "2026.2.15"
}

function Bootstrap-OpenClawRuntimeFromRegistry([string]$TargetDir, [string]$Version) {
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("openclaw-bootstrap-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $bootstrapPackage = @{
        name = "openclaw-runtime-bootstrap"
        private = $true
        version = "0.0.0"
        dependencies = @{
            openclaw = $Version
        }
    } | ConvertTo-Json -Depth 6
    Set-Content -Path (Join-Path $tempRoot "package.json") -Value $bootstrapPackage -Encoding UTF8

    $npm = Get-Command npm -ErrorAction Stop
    Push-Location $tempRoot
    try {
        & $npm.Source install --omit=dev --no-package-lock --no-audit --silent
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }

    $installedRoot = Join-Path $tempRoot "node_modules\openclaw"
    if (-not (Test-Path $installedRoot)) {
        throw "OpenClaw package was not installed from registry into $installedRoot"
    }

    Copy-DirectoryContents $installedRoot $TargetDir
    Copy-Tree (Join-Path $tempRoot "node_modules") (Join-Path $TargetDir "node_modules")

    $nestedRuntime = Join-Path $TargetDir "node_modules\openclaw"
    if (Test-Path $nestedRuntime) {
        Invoke-CmdChecked "rmdir /s /q `"$nestedRuntime`""
    }

    if (Test-Path $tempRoot) {
        Invoke-CmdChecked "rmdir /s /q `"$tempRoot`""
    }
}

$sourcePath = Resolve-FullPath $Source
$targetPath = Resolve-FullPath $Target

$targetParent = Split-Path -Parent $targetPath

if ($targetParent -and -not (Test-Path $targetParent)) {
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
}

if (Test-OpenClawRuntimeReady $targetPath) {
    Write-Host "Reusing existing OpenClaw runtime at $targetPath"
    exit 0
}

if (Test-Path $targetPath) {
    $staleName = "{0}-stale-{1}" -f (Split-Path -Leaf $targetPath), (Get-Date -Format "yyyyMMddHHmmss")
    $stalePath = Join-Path $targetParent $staleName
    Move-Item -Force $targetPath $stalePath
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "rmdir /s /q `"$stalePath`"" -WindowStyle Hidden | Out-Null
}

Initialize-ProxyEnvironment

if (Test-Path $sourcePath) {
    $pnpm = Get-Command pnpm -ErrorAction Stop
    Write-Host "Preparing OpenClaw runtime from local source $sourcePath to $targetPath"
    Push-Location $sourcePath
    try {
        & $pnpm.Source --filter . deploy --legacy --prod $targetPath
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "pnpm deploy failed with exit code $LASTEXITCODE"
    }
} else {
    $runtimeVersion = Get-OpenClawRuntimeVersion $sourcePath $targetPath
    Write-Host "OpenClaw source path missing; bootstrapping openclaw@$runtimeVersion from npm registry"
    Bootstrap-OpenClawRuntimeFromRegistry $targetPath $runtimeVersion
}

Materialize-HoistedNodeModules $targetPath
Prune-OpenClawRuntime $targetPath
Materialize-OpenClawRuntime $targetPath

if (-not (Test-OpenClawRuntimeReady $targetPath)) {
    throw "OpenClaw runtime is incomplete after deploy: $targetPath"
}
