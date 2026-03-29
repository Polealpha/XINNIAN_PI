param(
    [string]$AppDir = ".\release\win-unpacked",
    [string]$OutputFile = ".\release\EmoResonance Setup 0.0.1.exe",
    [string]$ProductName = "EmoResonance",
    [string]$Version = "0.0.1",
    [string]$InstallSubdir = "EmoResonance"
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $PathValue))
}

function Get-MakensisPath {
    $candidates = @(
        "C:\Users\jingk\AppData\Local\electron-builder\Cache\nsis\nsis-3.0.4.1\makensis.exe",
        "C:\Users\jingk\AppData\Local\electron-builder\Cache\nsis\nsis-3.0.4.1\Bin\makensis.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $resolved = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($resolved) {
        return $resolved.Source
    }

    throw "makensis.exe not found"
}

function Copy-MaterializedTree([string]$SourceDir, [string]$DestinationDir) {
    if (Test-Path $DestinationDir) {
        Remove-Item -Recurse -Force $DestinationDir
    }

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null

    $null = & robocopy $SourceDir $DestinationDir /MIR /MT:32 /R:1 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP
    if ($LASTEXITCODE -ge 8) {
        $requiredPaths = @(
            "EmoResonance.exe",
            "resources\app.asar",
            "resources\openclaw\openclaw.mjs",
            "resources\bridge-runtime\backend\main.py"
        )
        $missingPaths = @(
            $requiredPaths | Where-Object {
                -not (Test-Path (Join-Path $DestinationDir $_))
            }
        )
        if ($missingPaths.Count -gt 0) {
            throw "Failed to materialize application tree with robocopy (exit $LASTEXITCODE). Missing: $($missingPaths -join ', ')"
        }
        Write-Warning "robocopy returned exit $LASTEXITCODE while materializing junction-heavy runtime tree, but required files are present. Continuing."
    }
}

function Get-PathSignature([string]$PathValue) {
    if (-not (Test-Path $PathValue)) {
        return [ordered]@{
            path = $PathValue
            exists = $false
        }
    }

    $item = Get-Item $PathValue
    if (-not $item.PSIsContainer) {
        return [ordered]@{
            path = $PathValue
            exists = $true
            type = "file"
            length = $item.Length
            lastWriteTicksUtc = $item.LastWriteTimeUtc.Ticks
        }
    }

    $files = @(Get-ChildItem -Path $PathValue -Recurse -File -Force)
    $latestTicks = 0L
    [int64]$totalBytes = 0
    foreach ($file in $files) {
        $totalBytes += $file.Length
        if ($file.LastWriteTimeUtc.Ticks -gt $latestTicks) {
            $latestTicks = $file.LastWriteTimeUtc.Ticks
        }
    }

    return [ordered]@{
        path = $PathValue
        exists = $true
        type = "directory"
        fileCount = $files.Count
        totalBytes = $totalBytes
        latestFileTicksUtc = $latestTicks
    }
}

function Get-BuildSignatureJson([string]$SourceDir) {
    $targets = [ordered]@{
        payloadFormat = "tar.gz-v2"
        appExe = Get-PathSignature (Join-Path $SourceDir "EmoResonance.exe")
        appAsar = Get-PathSignature (Join-Path $SourceDir "resources\app.asar")
        openclaw = Get-PathSignature (Join-Path $SourceDir "resources\openclaw")
        bridgeRuntime = Get-PathSignature (Join-Path $SourceDir "resources\bridge-runtime")
    }
    return ($targets | ConvertTo-Json -Depth 8 -Compress)
}

function New-PayloadArchive([string]$SourceDir) {
    $stagingDir = Join-Path ([System.IO.Path]::GetTempPath()) ("emoresonance-stage-" + [System.Guid]::NewGuid().ToString("N"))
    $payloadTarPath = Join-Path ([System.IO.Path]::GetTempPath()) ("emoresonance-payload-" + [System.Guid]::NewGuid().ToString("N") + ".tar.gz")
    if (Test-Path $stagingDir) {
        Remove-Item -Recurse -Force $stagingDir
    }
    if (Test-Path $payloadTarPath) {
        Remove-Item -Force $payloadTarPath
    }

    Copy-MaterializedTree -SourceDir $SourceDir -DestinationDir $stagingDir

    & tar.exe -czf $payloadTarPath -C $stagingDir .
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $payloadTarPath)) {
        throw "Failed to create payload.tar.gz"
    }

    return @{
        PayloadArchivePath = $payloadTarPath
        StagingDir = $stagingDir
    }
}

function Split-PayloadArchive([string]$PayloadArchivePath, [int64]$ChunkSizeBytes = 1073741824) {
    $partsDir = Join-Path ([System.IO.Path]::GetTempPath()) ("emoresonance-payload-parts-" + [System.Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $partsDir | Out-Null

    $buffer = New-Object byte[] (4MB)
    $partPaths = [System.Collections.Generic.List[string]]::new()
    $partIndex = 0

    $input = [System.IO.File]::OpenRead($PayloadArchivePath)
    try {
        while ($input.Position -lt $input.Length) {
            $partPath = Join-Path $partsDir ("payload.part{0:D3}" -f $partIndex)
            $output = [System.IO.File]::Create($partPath)
            try {
                [int64]$written = 0
                while ($written -lt $ChunkSizeBytes -and $input.Position -lt $input.Length) {
                    $remaining = [Math]::Min($buffer.Length, $ChunkSizeBytes - $written)
                    $read = $input.Read($buffer, 0, [int]$remaining)
                    if ($read -le 0) {
                        break
                    }
                    $output.Write($buffer, 0, $read)
                    $written += $read
                }
            } finally {
                $output.Dispose()
            }
            $partPaths.Add($partPath)
            $partIndex += 1
        }
    } finally {
        $input.Dispose()
    }

    return @{
        PartsDirectory = $partsDir
        PartPaths = $partPaths
    }
}

function Get-OrCreateCachedPayloadBundle([string]$SourceDir, [string]$CacheDir) {
    if (-not (Test-Path $CacheDir)) {
        New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    }

    $signatureJson = Get-BuildSignatureJson $SourceDir
    $manifestPath = Join-Path $CacheDir "payload-manifest.json"
    $cachedPayloadTarPath = Join-Path $CacheDir "payload.tar.gz"
    $cachedPartPaths = @(Get-ChildItem -Path $CacheDir -Filter "payload.part*" -File -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -ExpandProperty FullName)

    if ((Test-Path $manifestPath) -and (Test-Path $cachedPayloadTarPath) -and $cachedPartPaths.Count -gt 0) {
        $existingSignatureJson = Get-Content -Path $manifestPath -Raw
        if ($existingSignatureJson -eq $signatureJson) {
            Write-Host "Reusing cached installer payload."
            return @{
                PayloadArchivePath = $cachedPayloadTarPath
                PartPaths = $cachedPartPaths
                TempPayloadArchivePath = $null
                TempPartsDirectory = $null
                TempStagingDirectory = $null
            }
        }
    }

    $payloadBundle = New-PayloadArchive $SourceDir
    $tempPayloadArchivePath = $payloadBundle.PayloadArchivePath
    $tempStagingDirPath = $payloadBundle.StagingDir
    $partsBundle = Split-PayloadArchive -PayloadArchivePath $tempPayloadArchivePath
    $tempPartsDirPath = $partsBundle.PartsDirectory
    $tempPartPaths = $partsBundle.PartPaths

    foreach ($existingPart in Get-ChildItem -Path $CacheDir -Filter "payload.part*" -File -ErrorAction SilentlyContinue) {
        Remove-Item -Force $existingPart.FullName -ErrorAction SilentlyContinue
    }

    Copy-Item -Force $tempPayloadArchivePath $cachedPayloadTarPath
    $cachedPartPaths = @()
    foreach ($tempPartPath in $tempPartPaths) {
        $cachedPartPath = Join-Path $CacheDir ([System.IO.Path]::GetFileName($tempPartPath))
        Copy-Item -Force $tempPartPath $cachedPartPath
        $cachedPartPaths += $cachedPartPath
    }
    Set-Content -Path $manifestPath -Value $signatureJson -Encoding UTF8

    return @{
        PayloadArchivePath = $cachedPayloadTarPath
        PartPaths = $cachedPartPaths
        TempPayloadArchivePath = $tempPayloadArchivePath
        TempPartsDirectory = $tempPartsDirPath
        TempStagingDirectory = $tempStagingDirPath
    }
}

$appDirPath = Resolve-FullPath $AppDir
$outputFilePath = Resolve-FullPath $OutputFile
$outputDir = Split-Path -Parent $outputFilePath
$workspaceRoot = Resolve-FullPath (Join-Path $PSScriptRoot "..")
$appWindowsRoot = Join-Path $workspaceRoot "app windows"
$iconPath = Join-Path $appWindowsRoot "assets\app-icon.ico"

if (-not (Test-Path $appDirPath)) {
    throw "AppDir not found: $appDirPath"
}

if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

if (Test-Path $outputFilePath) {
    Remove-Item -Force $outputFilePath
}

$makensis = Get-MakensisPath
$payloadCacheDir = Join-Path $outputDir "installer-cache"
$payloadBundle = Get-OrCreateCachedPayloadBundle -SourceDir $appDirPath -CacheDir $payloadCacheDir
$payloadArchivePath = $payloadBundle.PayloadArchivePath
$payloadPartPaths = $payloadBundle.PartPaths
$tempPayloadArchivePath = $payloadBundle.TempPayloadArchivePath
$payloadPartsDirPath = $payloadBundle.TempPartsDirectory
$stagingDirPath = $payloadBundle.TempStagingDirectory
$nsisScriptPath = Join-Path $outputDir ("emoresonance-installer-" + [System.Guid]::NewGuid().ToString("N") + ".nsi")

$escapedOutput = $outputFilePath.Replace('\', '\\')
$escapedIcon = $iconPath.Replace('\', '\\')
$escapedInstallSubdir = $InstallSubdir.Replace('"', '$\"')
$escapedProductName = $ProductName.Replace('"', '$\"')
$escapedVersion = $Version.Replace('"', '$\"')
$nsisPayloadFiles = ($payloadPartPaths | ForEach-Object {
    $escapedPartPath = $_.Replace('\', '\\')
    $partName = [System.IO.Path]::GetFileName($_)
    "  File /oname=$partName ""$escapedPartPath"""
}) -join [Environment]::NewLine
$payloadStitchBlock = if ($payloadPartPaths.Count -eq 1) {
    $singlePartName = [System.IO.Path]::GetFileName($payloadPartPaths[0])
    '  Rename "$INSTDIR\' + $singlePartName + '" "$INSTDIR\payload.tar.gz"'
} else {
    $payloadPartList = ($payloadPartPaths | ForEach-Object {
        '"$INSTDIR\' + [System.IO.Path]::GetFileName($_) + '"'
    }) -join "+"
    @(
        '  nsExec::ExecToStack ''cmd /c copy /b /y ' + $payloadPartList + ' "$INSTDIR\payload.tar.gz"'''
        '  Pop $0'
        '  Pop $1'
        '  StrCmp $0 "0" +3'
        '    DetailPrint "Payload stitch failed: $1"'
        '    Abort "Failed to assemble application payload."'
    ) -join [Environment]::NewLine
}
$payloadPartDeleteLines = ($payloadPartPaths | ForEach-Object {
    "  Delete `"$INSTDIR\{0}`"" -f [System.IO.Path]::GetFileName($_)
}) -join [Environment]::NewLine

$nsisScript = @'
Unicode true
ManifestDPIAware true
RequestExecutionLevel user
CRCCheck on
SetCompress off

Name "__PRODUCT_NAME__"
OutFile "__OUTPUT_FILE__"
InstallDir "$LOCALAPPDATA\Programs\__INSTALL_SUBDIR__"
InstallDirRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "InstallLocation"
Icon "__ICON_PATH__"
UninstallIcon "__ICON_PATH__"
BrandingText "__PRODUCT_NAME__ __VERSION__"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetShellVarContext current

  IfFileExists "$INSTDIR\Uninstall EmoResonance.exe" 0 +3
    ExecWait '"$INSTDIR\Uninstall EmoResonance.exe" /S _?=$INSTDIR'
    Sleep 1000

  RMDir /r "$INSTDIR"
  CreateDirectory "$INSTDIR"
  SetOutPath "$INSTDIR"
__PAYLOAD_FILES__
  File /oname=uninstallerIcon.ico "__ICON_PATH__"

__PAYLOAD_STITCH_BLOCK__

  nsExec::ExecToStack '"$SYSDIR\tar.exe" -xzf "$INSTDIR\payload.tar.gz" -C "$INSTDIR"'
  Pop $0
  Pop $1
  StrCmp $0 "0" +3
    DetailPrint "Payload extraction failed: $1"
    Abort "Failed to extract application payload."

__PAYLOAD_DELETE_LINES__
  Delete "$INSTDIR\payload.tar.gz"
  WriteUninstaller "$INSTDIR\Uninstall EmoResonance.exe"
  CreateDirectory "$SMPROGRAMS\__PRODUCT_NAME__"
  CreateShortcut "$SMPROGRAMS\__PRODUCT_NAME__\__PRODUCT_NAME__.lnk" "$INSTDIR\EmoResonance.exe"
  CreateShortcut "$DESKTOP\__PRODUCT_NAME__.lnk" "$INSTDIR\EmoResonance.exe"

  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "DisplayName" "__PRODUCT_NAME__ __VERSION__"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "DisplayVersion" "__VERSION__"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "DisplayIcon" "$INSTDIR\uninstallerIcon.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "UninstallString" '"$INSTDIR\Uninstall EmoResonance.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "QuietUninstallString" '"$INSTDIR\Uninstall EmoResonance.exe" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$DESKTOP\__PRODUCT_NAME__.lnk"
  Delete "$SMPROGRAMS\__PRODUCT_NAME__\__PRODUCT_NAME__.lnk"
  RMDir "$SMPROGRAMS\__PRODUCT_NAME__"
  Delete /REBOOTOK "$INSTDIR\Uninstall EmoResonance.exe"
  Delete /REBOOTOK "$INSTDIR\uninstallerIcon.ico"
  RMDir /r /REBOOTOK "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance"
SectionEnd
'@

$nsisScript = $nsisScript.Replace('__PRODUCT_NAME__', $escapedProductName)
$nsisScript = $nsisScript.Replace('__VERSION__', $escapedVersion)
$nsisScript = $nsisScript.Replace('__OUTPUT_FILE__', $escapedOutput)
$nsisScript = $nsisScript.Replace('__INSTALL_SUBDIR__', $escapedInstallSubdir)
$nsisScript = $nsisScript.Replace('__ICON_PATH__', $escapedIcon)
$nsisScript = $nsisScript.Replace('__PAYLOAD_FILES__', $nsisPayloadFiles)
$nsisScript = $nsisScript.Replace('__PAYLOAD_STITCH_BLOCK__', $payloadStitchBlock)
$nsisScript = $nsisScript.Replace('__PAYLOAD_DELETE_LINES__', $payloadPartDeleteLines)

Set-Content -Path $nsisScriptPath -Value $nsisScript -Encoding UTF8

try {
    & $makensis $nsisScriptPath
    if ($LASTEXITCODE -ne 0) {
        throw "makensis failed with exit code $LASTEXITCODE"
    }
    Write-Host "Built installer: $outputFilePath"
} finally {
    if (Test-Path $nsisScriptPath) {
        Remove-Item -Force $nsisScriptPath -ErrorAction SilentlyContinue
    }
    if ($tempPayloadArchivePath -and (Test-Path $tempPayloadArchivePath)) {
        Remove-Item -Force $tempPayloadArchivePath -ErrorAction SilentlyContinue
    }
    if ($payloadPartsDirPath -and (Test-Path $payloadPartsDirPath)) {
        Remove-Item -Recurse -Force $payloadPartsDirPath -ErrorAction SilentlyContinue
    }
    if ($stagingDirPath -and (Test-Path $stagingDirPath)) {
        Remove-Item -Recurse -Force $stagingDirPath -ErrorAction SilentlyContinue
    }
}
