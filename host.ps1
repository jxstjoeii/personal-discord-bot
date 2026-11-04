$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$logDir = Join-Path $env:LOCALAPPDATA "PatriciaBot"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "bot.log"
if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 2MB)) {
    Move-Item $logFile "$logFile.old" -Force
}

function Write-Log([string]$message) {
    Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message)
}

$mutex = New-Object System.Threading.Mutex($false, "Local\PatriciaBot")
if (-not $mutex.WaitOne(0)) {
    Write-Log "Already running, so this start was skipped."
    exit 0
}

try {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Write-Log "Missing .venv. Run run.ps1 once from this folder."
        exit 1
    }
    if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
        Write-Log "Missing .env."
        exit 1
    }
    $running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "bot\.py" }
    if ($running) {
        Write-Log "A bot.py process is already running, so this start was skipped."
        exit 0
    }
    Write-Log "Starting Patricia Bot."
    $ErrorActionPreference = "Continue"
    & cmd.exe /c "`"$python`" -u bot.py >> `"$logFile`" 2>&1"
    Write-Log "Patricia Bot exited with code $LASTEXITCODE."
    if ($null -eq $LASTEXITCODE) { exit 1 }
    exit $LASTEXITCODE
}
finally {
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
}
