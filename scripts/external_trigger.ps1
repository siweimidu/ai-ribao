<#
.SYNOPSIS
    External scheduler for the AI Daily workflow.

.DESCRIPTION
    GitHub Actions schedule is best-effort: the docs say events may be delayed under load and
    that queued jobs may be dropped. Measured over the week to 2026-10-25, daily.yml fired 2 or
    3 times on days configured for 3, and the 12:00 Beijing slot produced no run at all on
    2026-10-21.

    Two defences already exist inside GitHub: six triggers per slot, and a watchdog every two
    hours. Both live on the same scheduler that is dropping events, so neither recovers from a
    window GitHub never opened.

    This runs on the local machine, on the Windows Task Scheduler, and asks the same question
    from a different clock.

.NOTES
    Idempotent. The daily workflow gates on date + slot, so a redundant dispatch is one no-op
    run rather than a duplicate issue.
#>

[CmdletBinding()]
param(
    [string]$Repo = "siweimidu/ai-ribao",
    [string]$Workflow = "daily.yml"
)

$ErrorActionPreference = "Stop"

$logDir = Join-Path $PSScriptRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("trigger-" + (Get-Date -Format "yyyy-MM") + ".log")

function Write-Log {
    param([string]$Message)
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

$repoRoot = Split-Path $PSScriptRoot -Parent
$checker = Join-Path $repoRoot "scripts\missing_slots.py"
if (-not (Test-Path $checker)) {
    Write-Log "FATAL missing_slots.py not found at $checker"
    exit 2
}

$env:GITHUB_REPOSITORY = $Repo
try {
    $raw = & python $checker 2>&1 | Out-String
} catch {
    Write-Log ("FATAL checker threw: " + $_.Exception.Message)
    exit 2
}

$retry = $false
$reason = ""
foreach ($line in ($raw -split "`n")) {
    $t = $line.Trim()
    if ($t -match "^retry=(.+)$") { $retry = ($matches[1].Trim() -eq "true") }
    if ($t -match "^reason=(.+)$") { $reason = $matches[1].Trim() }
}

if (-not $reason) {
    $reason = ($raw -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
}

if (-not $retry) {
    Write-Log ("nothing missing -- " + $reason)
    exit 0
}

Write-Log ("dispatching: " + $reason)
$out = & gh workflow run $Workflow --repo $Repo -f force=false 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) {
    Write-Log ("dispatch FAILED (exit " + $LASTEXITCODE + "): " + $out.Trim())
    exit 1
}
Write-Log "dispatched"
exit 0