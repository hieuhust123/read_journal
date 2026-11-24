# Registers a Windows scheduled task that builds the research digest every day and opens it in
# your browser when it is ready.
# Runs as you, only while you are logged in (needed for your Claude Code login); if the PC was off
# or asleep at the scheduled time, it runs as soon as possible afterwards.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1            # 08:00 daily
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -At 07:30
#   powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove
param(
    [string]$At = "08:00",
    [string]$TaskName = "ReadJournalDigest",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task '$TaskName'."
    return
}

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "Not found: $pythonw. Create the venv first (see README)." }

# --open: show the finished digest in the default browser.
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "read_journal.py --open" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Daily research digest (d:\read_journal). Output: digests\latest.html" -Force | Out-Null
Write-Output "Scheduled '$TaskName' daily at $At -> $repo\digests\latest.html (logs in $repo\logs)"
