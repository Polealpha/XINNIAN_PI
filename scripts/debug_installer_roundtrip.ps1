param(
    [string]$SourceDir = "E:\Desktop\chonggou\app windows\release\win-unpacked",
    [string]$StageDir = "$env:TEMP\emo-stage-manual",
    [string]$PayloadTar = "$env:TEMP\emo-manual-payload.tar",
    [string]$OutDir = "$env:TEMP\emo-manual-out"
)

$ErrorActionPreference = "Stop"

foreach ($path in @($StageDir, $OutDir)) {
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
    }
}
if (Test-Path $PayloadTar) {
    Remove-Item -Force $PayloadTar
}

New-Item -ItemType Directory -Path $StageDir | Out-Null
New-Item -ItemType Directory -Path $OutDir | Out-Null

$null = & robocopy $SourceDir $StageDir /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP
Write-Host "ROBOCOPY_EXIT=$LASTEXITCODE"

& tar.exe -cf $PayloadTar -C $StageDir .
Write-Host "TAR_CREATE_EXIT=$LASTEXITCODE"

& tar.exe -xf $PayloadTar -C $OutDir
Write-Host "TAR_EXTRACT_EXIT=$LASTEXITCODE"

$checks = [ordered]@{
    "OPENCLAW_MJS" = (Test-Path (Join-Path $OutDir "resources\openclaw\openclaw.mjs"))
    "OPENCLAW_DIST" = (Test-Path (Join-Path $OutDir "resources\openclaw\dist\entry.js"))
    "ENGINE_DIR" = (Test-Path (Join-Path $OutDir "resources\bridge-runtime\engine"))
    "BACKEND_MAIN" = (Test-Path (Join-Path $OutDir "resources\bridge-runtime\backend\main.py"))
}

foreach ($entry in $checks.GetEnumerator()) {
    Write-Host "$($entry.Key)=$($entry.Value)"
}
