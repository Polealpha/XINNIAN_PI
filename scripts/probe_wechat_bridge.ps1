param(
    [string]$RepoRoot = "E:\Desktop\lunwen_qwen_publish",
    [string]$OpenClawRepo = "E:\Desktop\openclaw"
)

$ErrorActionPreference = "Stop"

$localAppData = $env:LOCALAPPDATA
$stateRoot = if ($localAppData) {
    Join-Path $localAppData "EmoResonance\assistant_data\openclaw_state"
} else {
    ""
}
$wechatStateDir = if ($stateRoot) {
    Join-Path $stateRoot "openclaw-weixin"
} else {
    ""
}
$repoWechatStateDir = Join-Path $RepoRoot "assistant_data\openclaw_state\openclaw-weixin"
$openclawJsonPath = if ($stateRoot) {
    Join-Path $stateRoot "openclaw.json"
} else {
    ""
}

$localWechatExe = $null
if ($localAppData) {
    $localWechatExe = Join-Path $localAppData "Tencent\WeChat\WeChat.exe"
}

$runtimeHints = @()
foreach ($path in @(
    (Join-Path $OpenClawRepo ".openclaw-workspace\.venv39\Lib\site-packages\pywechat\WechatAuto.py"),
    (Join-Path $OpenClawRepo ".openclaw-workspace\.venv39\Lib\site-packages\pyweixin\WechatAuto.py"),
    (Join-Path $OpenClawRepo ".openclaw-workspace\.trash\WeChatSetup.exe"),
    (Join-Path $OpenClawRepo ".openclaw-workspace\.trash\WeChatWin_4.1.7.exe"),
    (Join-Path $repoWechatStateDir "accounts.json"),
    $localWechatExe,
    "C:\Program Files\Tencent\WeChat\WeChat.exe",
    "C:\Program Files (x86)\Tencent\WeChat\WeChat.exe"
)) {
    if ($path -and (Test-Path -LiteralPath $path)) {
        $runtimeHints += (Resolve-Path -LiteralPath $path).Path
    }
}

$openclawProviders = @()
$openclawProfiles = @()
if ($openclawJsonPath -and (Test-Path -LiteralPath $openclawJsonPath)) {
    try {
        $payload = Get-Content -Raw -LiteralPath $openclawJsonPath | ConvertFrom-Json
        if ($payload.models.providers) {
            $openclawProviders = @($payload.models.providers.PSObject.Properties.Name)
        }
        if ($payload.auth.profiles) {
            $openclawProfiles = @($payload.auth.profiles.PSObject.Properties.Name)
        }
    } catch {
    }
}

$qrAssets = @()
if ($wechatStateDir -and (Test-Path -LiteralPath $wechatStateDir)) {
    $qrAssets = Get-ChildItem -Recurse -File -LiteralPath $wechatStateDir -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'qr|qrcode' } |
        Select-Object -First 8 -ExpandProperty FullName
}

$result = [ordered]@{
    repo_root = $RepoRoot
    openclaw_repo = $OpenClawRepo
    local_state_root = $stateRoot
    openclaw_json_path = $openclawJsonPath
    wechat_state_dir = $wechatStateDir
    repo_wechat_state_dir = $repoWechatStateDir
    wechat_state_exists = [bool]($wechatStateDir -and (Test-Path -LiteralPath $wechatStateDir))
    qr_assets = @($qrAssets)
    openclaw_provider_names = @($openclawProviders)
    openclaw_auth_profiles = @($openclawProfiles)
    runtime_hints = @($runtimeHints)
    likely_missing_bridge = -not ($wechatStateDir -and (Test-Path -LiteralPath $wechatStateDir)) -and ($openclawProviders -notcontains "wechat") -and ($openclawProviders -notcontains "wecom")
}

$result | ConvertTo-Json -Depth 8
