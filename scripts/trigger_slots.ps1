# External slot trigger -- the primary scheduler.
#
# GitHub's cron cannot be relied on for the three daily slots: measured drift of two to four
# hours, and on 2026-11-02 the 12:00 Beijing slot produced no run at all even though the
# workflow carries six attempts in that hour.
#
# This runs on the machine instead, every ten minutes across each slot window, so a slept
# laptop or a busy minute still lands the slot before the window closes.
#
# It only dispatches. The digest gate decides whether to build, so a redundant call costs
# seconds -- but a missed slot costs the whole issue.

param([string]$Repo = 'siweimidu/ai-ribao')

$ErrorActionPreference = 'Continue'

$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) {
    foreach ($p in @(
        'C:\Program Files\GitHub CLI\gh.exe',
        'C:\Program Files (x86)\GitHub CLI\gh.exe',
        "$env:LOCALAPPDATA\GitHubCLI\gh.exe"
    )) { if (Test-Path $p) { $gh = $p; break } }
}
if (-not $gh) { Write-Output 'gh not found'; exit 1 }

$log = Join-Path $PSScriptRoot 'trigger_slots.log'
function Say($text) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text"
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

# Already queued or running for this slot? Then this tick is a no-op.
$before = & $gh run list --repo $Repo --workflow=daily.yml --limit 1 --json createdAt,status 2>$null
$beforeAt = ($before | ConvertFrom-Json | Select-Object -First 1).createdAt
if ($beforeAt) {
    $age = ((Get-Date).ToUniversalTime() - [datetime]::Parse($beforeAt).ToUniversalTime()).TotalMinutes
    if ($age -lt 45) { Say "skip: a run started $([int]$age) min ago"; exit 0 }
}

Say "dispatch $Repo via $gh"
& $gh workflow run daily.yml --repo $Repo -f force=false 2>&1 | ForEach-Object { Say "  $_" }

# gh exits 0 even when the token lacks actions:write, so read the run list back.
Start-Sleep -Seconds 20
$after = & $gh run list --repo $Repo --workflow=daily.yml --limit 1 --json createdAt,status 2>$null
$afterAt = ($after | ConvertFrom-Json | Select-Object -First 1).createdAt
if ($afterAt -ne $beforeAt) {
    Say "queued: $afterAt"
} else {
    Say 'NOT QUEUED -- retrying once'
    & $gh workflow run daily.yml --repo $Repo -f force=false 2>&1 | ForEach-Object { Say "  $_" }
}