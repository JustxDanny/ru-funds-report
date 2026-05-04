# Scheduled-task entry. Invoked by Windows Task Scheduler Mon+Fri 09:00.
# Captures stdout+stderr to logs/YYYY-MM-DD_HHmm.log via cmd.exe redirection
# (PowerShell's 2>&1 wraps every stderr line as a NativeCommandError, which
# poisons the pipeline). Exit code propagates from python.

$root   = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
$ts     = Get-Date -Format 'yyyy-MM-dd_HHmm'
$log    = Join-Path $logDir "$ts.log"

New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Set-Location $root

# Resolve python — Task Scheduler runs with a clean PATH, so don't rely on PATH.
$pythonCandidates = @(
    'C:\Program Files\PyManager\python.exe',
    'C:\Program Files\Python313\python.exe',
    'C:\Program Files\Python312\python.exe',
    'C:\Program Files\Python311\python.exe',
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    "python.exe not found in expected locations" | Out-File -FilePath $log -Encoding utf8
    exit 2
}

# Force Python to emit UTF-8 — Windows console default codec can't encode Cyrillic.
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# Use [IO.File] for the banners so the log is consistent UTF-8 (no BOM mismatch
# with cmd.exe-redirected output which has no BOM either).
$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::AppendAllText($log, "=== $ts  start ===`r`n", $utf8)
& cmd.exe /c "`"$python`" -m funds_report >> `"$log`" 2>&1"
$rc = $LASTEXITCODE
[System.IO.File]::AppendAllText($log, "=== $ts  end (exit=$rc) ===`r`n", $utf8)
exit $rc
