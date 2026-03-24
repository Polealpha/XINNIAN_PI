param(
  [string]$Host = "0.0.0.0",
  [int]$Port = 28789
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

& .\start_wecom.ps1 -Host $Host -Port $Port
