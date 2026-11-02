# External slot trigger.
#
# GitHub's own cron is the weak link: measured drift of two to four hours, and slots that
# produced no run at all (2026-11-02 12:00 Beijing never fired). The in-repo watchdog cannot
# save that -- it is scheduled by the same timer. This task runs on this machine instead.
#
# It only dispatches. Whether the day actually builds is decided by the digest gate, which
# knows if today is already published or too early -- so a redundant call costs seconds.

param([string]$Repo = 'siweimidu/ai-ribao')

$ErrorActionPreference = 'Continue'

# Task Scheduler starts powershell.exe with a minimal PATH; do not assume gh is on it.
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) {
    foreach ($p in @(
        'C:\Program Files\GitHub CLI\gh.exe',
        'C:\Program Files (x86)\GitHub CLI\gh.exe',
        "$env:LOCALAPPDATA\GitHubCLI\gh.exe"
    )) {
        if (Test-Path $p) { $gh = $p; break }
    }
}
if (-not $gh) { Write-Output 'gh not found'; exit 1 }

$log = Join-Path $PSScriptRoot 'trigger_slots.log'
function Say($text) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text"
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

Say "dispatch $Repo via $gh"
& $gh workflow run daily.yml --repo $Repo -f force=false 2>&1 | ForEach-Object { Say "  $_" }

# Verify it actually queued. gh exits 0 even when the token lacks actions:write, so the run
# list is the only honest check.
Start-Sleep -Seconds 25
$runs = & $gh run list --repo $Repo --workflow=daily.yml --limit 1 --json createdAt,status 2>$null
Say "latest run: $runs"