# Restarts Patricia, for example after .\sync.ps1 pulled an update.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$taskName = "Patricia Bot"

# Pick up any new packages an update added (for example Pillow for pictures).
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Host "Checking packages..."
    & $python -m pip install --quiet --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements.txt")
}

$running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "bot\.py" })
foreach ($process in $running) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($running.Count -gt 0) {
    Write-Host "Stopped Patricia."
    Start-Sleep -Seconds 3
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $taskName
    Write-Host "Started her again in the background. She should be online in a few seconds."
} else {
    Start-Process wscript.exe -ArgumentList "`"$(Join-Path $PSScriptRoot 'start-hidden.vbs')`""
    Write-Host "Started her in the background. Run .\install-startup.ps1 once so she also starts by herself when you sign in."
}
