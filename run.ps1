$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env. Fill in your Discord token, user id, and Claude token (run .\setup-claude.ps1 to get it), then run this script again."
    exit 1
}

.\.venv\Scripts\python.exe bot.py
