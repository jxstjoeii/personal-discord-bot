# Signs Patricia in to your Claude subscription.
# It opens the browser, you approve, and it prints a token that lasts a year.
# Paste that token into .env as CLAUDE_CODE_OAUTH_TOKEN, then restart run.ps1.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$claude = Get-Command claude -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $claude -and (Test-Path .venv)) {
    # The Python package ships its own copy of Claude Code.
    $claude = Get-ChildItem .venv -Recurse -Filter "claude.exe" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName -First 1
}
if (-not $claude) {
    Write-Host "Claude Code was not found. Run .\run.ps1 once to install the packages, or install"
    Write-Host "Claude Code from https://code.claude.com, then run this script again."
    exit 1
}

Write-Host "Using $claude"
Write-Host "A browser window opens. Sign in with the Claude account that has your subscription."
& $claude setup-token
Write-Host ""
Write-Host "Copy the token above into .env as CLAUDE_CODE_OAUTH_TOKEN=..., then run .\run.ps1."
