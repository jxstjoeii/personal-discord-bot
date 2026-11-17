$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:GIT_TERMINAL_PROMPT = "0"

$logDir = Join-Path $env:LOCALAPPDATA "PatriciaBot"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "github-sync.log"

function Write-Log([string]$message) {
    Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message)
}

function Invoke-Git {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & git -c "user.name=jxstjoeii" -c "user.email=195534516+jxstjoeii@users.noreply.github.com" @args 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) {
        throw (($output | Out-String).Trim())
    }
    return $output
}

# Brings Patricia back if she is not running. It runs after the sync (in finally), so she
# starts with the newest code, and a failed sync can't skip it.
function Start-PatriciaIfStopped {
    try {
        $bot = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
            Where-Object { $_.CommandLine -match "bot\.py" }
        $starter = Join-Path $PSScriptRoot "start-hidden.vbs"
        if (-not $bot -and (Test-Path $starter)) {
            Start-Process -FilePath "wscript.exe" -ArgumentList "`"$starter`""
            Write-Log "Patricia was not running, so she was started in the background."
        }
    }
    catch {
        Write-Log "Could not check on Patricia: $($_.Exception.Message)"
    }
}

try {
try {
    Invoke-Git add -A | Out-Null
    $staged = @(Invoke-Git diff --cached --name-only | Where-Object { $_ -and $_.ToString().Trim() })
    if ($staged -contains ".env") {
        Invoke-Git reset HEAD -- .env | Out-Null
        Write-Log "Refused to commit .env."
        exit 1
    }
    if ($staged.Count -gt 0) {
        Invoke-Git commit -m "Update Patricia Bot from this PC." | Out-Null
    }
    Invoke-Git pull --rebase origin main | Out-Null
    if ($staged.Count -gt 0) {
        Invoke-Git push origin main | Out-Null
        Write-Log ("Pushed " + ($staged -join ", "))
    } else {
        Write-Log "No local changes."
    }
}
catch {
    $ErrorActionPreference = "Continue"
    git rebase --abort 2>&1 | Out-Null
    Write-Log $_.Exception.Message
    exit 1
}
}
finally {
    Start-PatriciaIfStopped
}
