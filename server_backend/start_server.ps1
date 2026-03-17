param(
    [string]$EnvFile = "$PSScriptRoot\\.env",
    [string]$Host = "",
    [int]$Port = 0,
    [int]$Workers = 0
)

$argsList = @("--env-file", $EnvFile)
if ($Host -ne "") { $argsList += @("--host", $Host) }
if ($Port -gt 0) { $argsList += @("--port", "$Port") }
if ($Workers -gt 0) { $argsList += @("--workers", "$Workers") }

python "$PSScriptRoot\\run_server.py" @argsList

