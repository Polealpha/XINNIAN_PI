param(
    [ValidateSet("bf16", "autoround")]
    [string]$Mode = "bf16",
    [string]$HelperPath = "E:\codex_ssh_helper.ps1",
    [switch]$SkipPoll
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $HelperPath)) {
    throw "SSH helper not found: $HelperPath"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$tempDir = Join-Path $env:TEMP "lunwen-qwen-switch"
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$remoteScriptPath = Join-Path $tempDir "switch-qwen-omni-$Mode.sh"

$remoteScript = if ($Mode -eq "autoround") {
@'
set -euo pipefail
BASE=/root/services/qwen3_omni_runtime
BF16="$BASE/modelscope_download/Qwen3-Omni-30B-A3B-Instruct"
SRC="$BASE/huggingface_download/Intel-Qwen3-Omni-30B-A3B-Instruct-int4-AutoRound"
FIX="$BASE/huggingface_download/Intel-Qwen3-Omni-30B-A3B-Instruct-int4-AutoRound-runtimefix"

if [ ! -d "$SRC" ]; then
  echo "missing_autoround_src:$SRC" >&2
  exit 1
fi
if [ ! -d "$BF16" ]; then
  echo "missing_bf16_src:$BF16" >&2
  exit 1
fi

rm -rf "$FIX"
mkdir -p "$FIX"
cp -al "$SRC"/. "$FIX"/
cp -f "$BF16"/preprocessor_config.json "$FIX"/preprocessor_config.json
cp -f "$BF16"/tokenizer_config.json "$FIX"/tokenizer_config.json
cp -f "$BF16"/vocab.json "$FIX"/vocab.json
cp -f "$BF16"/merges.txt "$FIX"/merges.txt
cp -f "$BF16"/configuration.json "$FIX"/configuration.json || true
cp -f "$BF16"/chat_template.json "$FIX"/chat_template.json || true
rm -f "$FIX"/tokenizer.json

export QWEN3_OMNI_MODEL_DIR="$FIX"
export QWEN3_OMNI_MAX_MODEL_LEN=131072
export QWEN3_OMNI_PORT=8091
"$BASE"/stop_qwen3_omni.sh || true
sleep 5
"$BASE"/start_qwen3_omni.sh
cat "$BASE"/runtime/server.pid
'@
} else {
@'
set -euo pipefail
BASE=/root/services/qwen3_omni_runtime
BF16="$BASE/modelscope_download/Qwen3-Omni-30B-A3B-Instruct"
if [ ! -d "$BF16" ]; then
  echo "missing_bf16_src:$BF16" >&2
  exit 1
fi
export QWEN3_OMNI_MODEL_DIR="$BF16"
export QWEN3_OMNI_MAX_MODEL_LEN=24576
export QWEN3_OMNI_PORT=8091
"$BASE"/stop_qwen3_omni.sh || true
sleep 5
"$BASE"/start_qwen3_omni.sh
cat "$BASE"/runtime/server.pid
'@
}

[System.IO.File]::WriteAllText($remoteScriptPath, $remoteScript, [System.Text.UTF8Encoding]::new($false))
try {
    Write-Host "[switch] mode=$Mode"
    & $HelperPath -RemoteScriptFile $remoteScriptPath
    if ($SkipPoll) {
        return
    }

    $deadline = (Get-Date).AddMinutes(8)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8091/v1/models" -TimeoutSec 10
            if ($resp.data) {
                $ready = $true
                $model = $resp.data[0]
                Write-Host "[ready] id=$($model.id)"
                Write-Host "[ready] max_model_len=$($model.max_model_len)"
                break
            }
        } catch {
            Start-Sleep -Seconds 10
        }
    }
    if (-not $ready) {
        throw "Timed out waiting for http://127.0.0.1:8091/v1/models"
    }
} finally {
    Remove-Item -LiteralPath $remoteScriptPath -Force -ErrorAction SilentlyContinue
}
