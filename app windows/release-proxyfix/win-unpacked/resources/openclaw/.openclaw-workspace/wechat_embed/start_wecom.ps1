param(
    [string]$Host = "0.0.0.0",
    [int]$Port = 28789
)

$root = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $root ".venv39\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    py -3.9 -m venv (Join-Path $root ".venv39")
}

& $pythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

$envFile = Join-Path $PSScriptRoot ".env.wecom"
$envExample = Join-Path $PSScriptRoot ".env.wecom.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "Created $envFile from template. Fill it before first run."
}

& $pythonExe (Join-Path $PSScriptRoot "wecom_gateway.py") run --env-file $envFile --host $Host --port $Port
