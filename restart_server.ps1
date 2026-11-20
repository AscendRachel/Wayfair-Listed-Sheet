# Restart the Wayfair Catalog server on this PC: closes the old server window(s), then opens a fresh one.
# Run it with restart_server.bat (double-click), or: powershell -ExecutionPolicy Bypass -File restart_server.ps1
param([switch]$Force)                                 # -Force: restart even while an import is running (it would be cut off)
$ErrorActionPreference = "SilentlyContinue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = if ($env:GT_PORT) { [int]$env:GT_PORT } else { 8001 }

# 0. never cut off an import that is still running
$db = Join-Path $here "data\optimizer.db"
if (-not $Force -and (Test-Path $db)) {
    $check = 'import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); print(sum(1 for (v,) in c.execute(''select value from settings where key in (?,?)'', (''import_job'',''wayfair_job'')) if json.loads(v).get(''state'')==''running''))'
    $running = & (Join-Path $here ".venv\Scripts\python.exe") -I -c $check $db
    if ("$running".Trim() -ne "0") {
        "An import is still running. Wait for it to finish, then restart (or run with -Force to cut it off)."
        exit 2
    }
}

# 1. the old server windows: started by this script, by start_server.bat in this folder, or whatever window hosts the server on the port
$windows = @(Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | Where-Object {
    $_.CommandLine -like "*Wayfair Catalog - SERVER*" -or $_.CommandLine -like "*$here\start_server.bat*" } | ForEach-Object { $_.ProcessId })
$server = Get-NetTCPConnection -LocalPort $port -State Listen | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($id in $server) {
    $p = $id
    while ($p) {                                      # walk up from the server process to the console window that runs it
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$p"
        if (-not $proc) { break }
        if ($proc.Name -eq "cmd.exe") { $windows += $proc.ProcessId; break }
        $p = $proc.ParentProcessId
    }
    Stop-Process -Id $id -Force
}
foreach ($w in ($windows | Sort-Object -Unique)) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$w" | Where-Object { $_.Name -like "python*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Stop-Process -Id $w -Force                        # closes the window
}
Start-Sleep -Seconds 1

# 2. a fresh server window (no browser tab is opened, unlike start_server.bat)
Start-Process -FilePath "cmd.exe" -WorkingDirectory $here -ArgumentList '/k', 'title Wayfair Catalog - SERVER (keep this window open) & .venv\Scripts\python.exe run.py'

# 3. wait until it answers
foreach ($i in 1..20) {
    try { if ((Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/api/ping" -TimeoutSec 2).StatusCode -eq 200) { "Wayfair Catalog restarted: http://localhost:$port"; exit 0 } } catch { }
    Start-Sleep -Milliseconds 700
}
"The server didn't answer on port $port. Look at the new server window for the error."
exit 1
