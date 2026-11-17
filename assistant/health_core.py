"""Weekly PC health check: fixed, read-only checks. Nothing here changes the PC."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from assistant import pc

CHECKS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$r = [ordered]@{}
$r.disks = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    [ordered]@{ name = $_.DeviceID; freeGb = [math]::Round($_.FreeSpace / 1GB, 1); sizeGb = [math]::Round($_.Size / 1GB, 1) }
})
$os = Get-CimInstance Win32_OperatingSystem
if ($os) {
    $r.uptimeDays = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalDays, 1)
    $r.memFreeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    $r.memTotalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
}
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
    $r.pendingUpdates = $found.Updates.Count
} catch { $r.pendingUpdates = $null }
$r.rebootPending = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
$task = Get-ScheduledTask -TaskName 'Patricia Bot'
$r.startupTask = if ($task) { [string]$task.State } else { 'missing' }
$service = Get-Service -Name 'Tailscale'
$r.tailscaleService = if ($service) { [string]$service.Status } else { 'missing' }
$exe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (Test-Path $exe) {
    $status = (& $exe status --json 2>$null | Out-String) | ConvertFrom-Json
    if ($status) {
        $r.tailscale = [string]$status.BackendState
        $r.tailscaleOnline = [bool]$status.Self.Online
    } else { $r.tailscale = 'not running' }
} else { $r.tailscale = 'not installed' }
$r | ConvertTo-Json -Depth 4 -Compress
"""


def run_checks(timeout: int = 150) -> dict:
    """Runs the checks hidden, with no window. Returns {} off Windows or on failure."""
    shell = pc.shell_path()
    if not pc.is_windows() or shell is None:
        return {}
    handle, path = tempfile.mkstemp(prefix="patricia-health-", suffix=".ps1")
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig") as file:
            file.write(CHECKS)
        done = subprocess.run(
            [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=pc.CREATE_NO_WINDOW,
        )
        text = done.stdout.decode("utf-8", "replace").strip()
        start = text.find("{")
        return json.loads(text[start:]) if start >= 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def log_problems(log_file: Path, now: datetime, days: int = 7) -> int:
    """Errors and crashes in Patricia's log over the last few days."""
    if not log_file.exists():
        return 0
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    count = 0
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-20000:]
    except OSError:
        return 0
    for line in lines:
        stamp = re.match(r"(\d{4}-\d{2}-\d{2})", line)
        if stamp and stamp.group(1) >= since and (" ERROR " in line or " CRITICAL " in line):
            count += 1
    return count


def report(data: dict, problems: int) -> str:
    if not data:
        return "🩺 I couldn't run the PC health check this time. It only works on the Windows PC."
    good, warn = [], []
    for disk in data.get("disks") or []:
        free, size = float(disk.get("freeGb") or 0), float(disk.get("sizeGb") or 0)
        line = f"{disk.get('name')} has {free:g} GB free of {size:g} GB"
        if size and (free / size < 0.10 or free < 20):
            warn.append(f"💾 {line}. Time to clear some space.")
        else:
            good.append(f"💾 {line}.")
    pending = data.get("pendingUpdates")
    if data.get("rebootPending"):
        warn.append("🔄 Windows needs a restart to finish installing updates.")
    elif pending:
        warn.append(f"🔄 {pending} Windows update(s) are waiting.")
    elif pending == 0:
        good.append("🔄 Windows is up to date.")
    uptime = data.get("uptimeDays")
    if uptime is not None and float(uptime) >= 14:
        warn.append(f"⏱️ The PC hasn't restarted in {float(uptime):g} days. A restart now and then keeps things snappy.")
    task = data.get("startupTask")
    if task in ("Ready", "Running"):
        good.append("🤖 My start-up task is set, so I come back by myself.")
    elif task:
        warn.append("🤖 My start-up task isn't installed. Run .\\install-startup.ps1 in my folder.")
    tail = data.get("tailscale")
    if tail == "Running" and data.get("tailscaleOnline", True):
        good.append("🌐 Tailscale is connected, so Remote Desktop from school will work.")
    elif tail:
        warn.append(f"🌐 Tailscale is {str(tail).lower()}, so Remote Desktop from school won't work. Open Tailscale and sign in.")
    if problems:
        warn.append(f"📋 My log has {problems} error(s) from the last week. Ask Claude to take a look.")
    else:
        good.append("📋 No errors in my log this week.")
    head = "🩺 **Weekly PC check-up**" + (": all good! ✨" if not warn else "")
    parts = [head]
    if warn:
        parts += ["", "**Needs a look**"] + [f"• {line}" for line in warn]
    if good:
        parts += ["", "**Looking good**"] + [f"• {line}" for line in good]
    return "\n".join(parts)
