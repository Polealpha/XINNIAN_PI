$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "..\\.venv39\\Scripts\\python.exe")) {
  py -3.9 -m venv ..\\.venv39
}

& ..\\.venv39\\Scripts\\python -m pip install -r .\\requirements.txt

if (-not (Test-Path ".\\config.json")) {
  Copy-Item .\\config.example.json .\\config.json
}

if (-not (Test-Path ".\\.env")) {
  Copy-Item .\\.env.example .\\.env
}

& ..\\.venv39\\Scripts\\python .\\wechat_bridge.py run
