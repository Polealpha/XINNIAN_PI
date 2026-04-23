$portUsers = Get-NetTCPConnection -LocalPort 18994 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if ($portUsers) {
    foreach ($pid in $portUsers) {
        try { Stop-Process -Id $pid -Force -ErrorAction Stop } catch {}
    }
}

$stdout = "E:\Desktop\lunwen\reports\local_minicpmo_exec_tunnel.stdout.log"
$stderr = "E:\Desktop\lunwen\reports\local_minicpmo_exec_tunnel.stderr.log"
Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue

$python = (Get-Command python.exe -ErrorAction Stop).Source
$cmd = 'start "" /b "' + $python + '" -u "E:\Desktop\lunwen\scripts\local_minicpmo_exec_tunnel.py" 1>"' + $stdout + '" 2>"' + $stderr + '"'
cmd /c $cmd | Out-Null
Start-Sleep -Seconds 2
$tunnelPid = Get-NetTCPConnection -LocalPort 18994 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    Select-Object -First 1
Write-Output ("PID=" + $tunnelPid)
