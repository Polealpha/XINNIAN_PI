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

$nsisScriptPath = Join-Path ([System.IO.Path]::GetTempPath()) ("emoresonance-installer-" + [System.Guid]::NewGuid().ToString("N") + ".nsi")
$makensis = Get-MakensisPath

$escapedAppDir = $appDirPath.Replace('\', '\\')
$escapedOutput = $outputFilePath.Replace('\', '\\')
$escapedIcon = $iconPath.Replace('\', '\\')
$escapedInstallSubdir = $InstallSubdir.Replace('"', '$\"')
$escapedProductName = $ProductName.Replace('"', '$\"')
$escapedVersion = $Version.Replace('"', '$\"')

$nsisScript = @'
Unicode true
ManifestDPIAware true
RequestExecutionLevel user
CRCCheck on
SetCompressor /FINAL /SOLID lzma

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
  File /r "__APP_DIR__\*"

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
  RMDir /r /REBOOTOK "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\EmoResonance"
SectionEnd
'@

$nsisScript = $nsisScript.Replace('__PRODUCT_NAME__', $escapedProductName)
$nsisScript = $nsisScript.Replace('__VERSION__', $escapedVersion)
$nsisScript = $nsisScript.Replace('__OUTPUT_FILE__', $escapedOutput)
$nsisScript = $nsisScript.Replace('__INSTALL_SUBDIR__', $escapedInstallSubdir)
$nsisScript = $nsisScript.Replace('__ICON_PATH__', $escapedIcon)
$nsisScript = $nsisScript.Replace('__APP_DIR__', $escapedAppDir)

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
}
