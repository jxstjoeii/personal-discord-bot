# Starts Patricia in the background when you sign in, with no window, and brings her
# back within 5 minutes if she ever stops. Run it once. Run it with -Remove to undo.
param([switch]$Remove)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$taskName = "Patricia Bot"

# Older start-up tasks that also run host.ps1 would compete with this one.
$old = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $actions = ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join " "
    $_.TaskName -ne $taskName -and $actions -match "host\.ps1|start-hidden\.vbs"
})
foreach ($task in $old) {
    Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Confirm:$false
    Write-Host "Removed an older start-up task: $($task.TaskPath)$($task.TaskName)"
}

# The hourly GitHub sync task ran sync.ps1 through powershell.exe directly, which opens a
# command prompt window for a moment every hour and can pull focus out of a game.
# Point it at sync-hidden.vbs instead, which runs the same sync with no window.
$syncVbs = Join-Path $PSScriptRoot "sync-hidden.vbs"
$syncTasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $actions = ($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join " "
    $actions -match "sync\.ps1" -and $actions -notmatch "sync-hidden\.vbs"
})
foreach ($task in $syncTasks) {
    try {
        $hidden = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$syncVbs`"" -WorkingDirectory $PSScriptRoot
        Set-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Action $hidden | Out-Null
        Write-Host "The hourly sync task '$($task.TaskName)' now runs with no window."
    }
    catch {
        Write-Host "Couldn't change the sync task '$($task.TaskName)': $($_.Exception.Message)"
        Write-Host "Try again from a PowerShell window opened with 'Run as administrator'."
    }
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Host "Patricia will no longer start by herself. If she is running now, she keeps running until you sign out or restart the PC."
    exit 0
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Run .\run.ps1 once first, so her packages are installed, then run this again."
    exit 1
}
if (-not (Test-Path ".env")) {
    Write-Host "The .env file is missing. Run .\run.ps1 once to create it."
    exit 1
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$vbs = Join-Path $PSScriptRoot "start-hidden.vbs"
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`"" -WorkingDirectory $PSScriptRoot

$atSignIn = New-ScheduledTaskTrigger -AtLogOn -User $user
$atSignIn.Delay = "PT20S"
# Every 5 minutes. While she is running this does nothing, because the task is still busy.
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Description "Runs Patricia, the Discord assistant, in the background. Made by install-startup.ps1." `
    -Action $action `
    -Trigger @($atSignIn, $watchdog) `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Installed. Patricia now starts by herself when you sign in, with no window."
Write-Host "If she stops, she comes back within 5 minutes. Use .\restart.ps1 after updates."

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "bot\.py" }
if ($running) {
    Write-Host "She is already running in another window. Close that window, or run .\restart.ps1, so the background copy takes over."
    exit 0
}

Start-ScheduledTask -TaskName $taskName
Write-Host "Starting her now..."
$log = Join-Path $env:LOCALAPPDATA "PatriciaBot\bot.log"
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if ((Test-Path $log) -and ((Get-Item $log).LastWriteTime -gt (Get-Date).AddSeconds(-40))) {
        $last = Get-Content $log -Tail 40 | Select-String "Logged in as" | Select-Object -Last 1
        if ($last) {
            Write-Host "She is online: $($last.Line)"
            exit 0
        }
    }
}
Write-Host "She hasn't logged in yet. Give her a minute, then check Discord. Her log is at $log"
