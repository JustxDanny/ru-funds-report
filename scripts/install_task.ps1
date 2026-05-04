# Installer for the Windows Task Scheduler entry. Run from any shell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_task.ps1
# Re-running replaces the existing task. Uninstall: schtasks /delete /tn funds-report /f

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$tmpl = Join-Path $root 'taskscheduler\funds-report.xml.tmpl'
$out  = Join-Path $root 'taskscheduler\funds-report.xml'

if (-not (Test-Path $tmpl)) { throw "missing template: $tmpl" }

$content = [System.IO.File]::ReadAllText($tmpl, [System.Text.Encoding]::UTF8)
$content = $content.Replace('__ROOT__', $root).Replace('__USER__', $env:USERNAME)
[System.IO.File]::WriteAllText($out, $content, [System.Text.UnicodeEncoding]::new($false, $true))

Write-Host "rendered: $out"

# Replace existing task if present (idempotent install).
& schtasks.exe /query /tn 'funds-report' 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "removing existing 'funds-report' task..."
    & schtasks.exe /delete /tn 'funds-report' /f | Out-Null
}

& schtasks.exe /create /tn 'funds-report' /xml $out
if ($LASTEXITCODE -ne 0) { throw "schtasks /create failed (exit $LASTEXITCODE)" }
Write-Host "installed. test fire with:"
Write-Host "    schtasks /run /tn funds-report"
Write-Host "view next run / history with:"
Write-Host "    schtasks /query /tn funds-report /v /fo list"
