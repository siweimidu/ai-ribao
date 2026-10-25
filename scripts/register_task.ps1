# Registers the external scheduler as a Windows Scheduled Task.
#
# Three times a day, two hours after each collection slot (04:00 / 12:00 / 20:00 Beijing).
# The two-hour gap matches the watchdog grace period: by then the slot should have published,
# and if it has not, the local clock dispatches it.
#
# Run once. Re-running updates the existing task rather than adding a second one.

$ErrorActionPreference = "Stop"

$taskName = "AI-Daily-ExternalTrigger"
$script = Join-Path $PSScriptRoot "external_trigger.ps1"

if (-not (Test-Path $script)) {
    Write-Error "external_trigger.ps1 not found next to this script"
    exit 1
}

# -WindowStyle Hidden so the task does not flash a console every time it fires.
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " + [char]34 + $script + [char]34)

$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At "06:30"),
    (New-ScheduledTaskTrigger -Daily -At "14:30"),
    (New-ScheduledTaskTrigger -Daily -At "22:30")
)

# StartWhenAvailable: a laptop asleep at 06:30 should still run when it wakes, rather than
# skipping the slot -- the same failure mode this task exists to work around.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Dispatches ai-ribao daily.yml when a slot is missing. GitHub schedule drops events under load." `
    -Force | Out-Null

Write-Host ("registered: " + $taskName)
Write-Host "  runs at 06:30 / 14:30 / 22:30 local time"
Write-Host ("  script: " + $script)
Write-Host ""
Write-Host "  verify with:  Get-ScheduledTask -TaskName $taskName | Format-List"
Write-Host "  run once now: Start-ScheduledTask -TaskName $taskName"
Write-Host "  remove:       Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"