"""Plan, check, and run PowerShell tasks on this PC.

Nothing in this file talks to Discord. The pc addon shows the plan with
Yes and No buttons and only calls run_plan after Joeii presses Yes.
"""

from __future__ import annotations

import csv
import getpass
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape

from assistant.config import Settings

MAX_STEPS = 8
OUTPUT_LIMIT = 3000
CREATE_NO_WINDOW = 0x08000000

# Ways to open a window that skip Open-Window. While a game is running these
# could land on the game screen, so a plan that uses them is refused.
_OPEN_PATTERNS = [
    r"(?<![\w$-])start-process(?![\w-])",
    r"(?<![\w$-])saps(?![\w-])",
    r"(?<![\w$-])start(?![\w-])",
    r"(?<![\w$-])invoke-item(?![\w-])",
    r"(?<![\w$-])ii(?![\w-])",
    r"(?<![\w$-])explorer(\.exe)?(?![\w-])",
    r"(?<![\w$-])shell:appsfolder",
    r"(?<![\w$-])rundll32(\.exe)?(?![\w-])",
    r"\[system\.diagnostics\.process\]::start",
]

# Loaded before every step. Open-Window is the only way a plan is allowed to
# open something that shows a window.
PREAMBLE = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$PatriciaGames = @(__GAMES__)

function Get-PatriciaGame {
    foreach ($name in $PatriciaGames) {
        $found = Get-Process -Name $name -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
            Select-Object -First 1
        if ($found) { return $found }
        $found = Get-Process -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found }
    }
    return $null
}

function Initialize-PatriciaWindows {
    if ('PatriciaWin' -as [type]) { return }
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PatriciaWin {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
}
'@
}

function Get-PatriciaSafeScreen($game) {
    Initialize-PatriciaWindows
    $screens = [System.Windows.Forms.Screen]::AllScreens
    $gameScreen = [System.Windows.Forms.Screen]::PrimaryScreen
    if ($game -and $game.MainWindowHandle -ne [IntPtr]::Zero) {
        $gameScreen = [System.Windows.Forms.Screen]::FromHandle($game.MainWindowHandle)
    }
    $discord = Get-Process -Name 'Discord', 'DiscordPTB', 'DiscordCanary' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
        Select-Object -First 1
    if ($discord) {
        $discordScreen = [System.Windows.Forms.Screen]::FromHandle($discord.MainWindowHandle)
        if ($discordScreen.DeviceName -ne $gameScreen.DeviceName) { return $discordScreen }
    }
    return $screens | Where-Object { $_.DeviceName -ne $gameScreen.DeviceName } | Select-Object -First 1
}

function Move-PatriciaWindow($handle, $screen) {
    $area = $screen.WorkingArea
    $width = [Math]::Min(1280, $area.Width)
    $height = [Math]::Min(820, $area.Height)
    $x = $area.X + [int](($area.Width - $width) / 2)
    $y = $area.Y + [int](($area.Height - $height) / 2)
    # 4 shows the window without taking focus from the game.
    [PatriciaWin]::ShowWindow($handle, 4) | Out-Null
    # 0x14 keeps the stacking order and does not activate the window.
    [PatriciaWin]::SetWindowPos($handle, [IntPtr]::Zero, $x, $y, $width, $height, 0x14) | Out-Null
}

function Open-Window {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList
    )
    $options = @{ FilePath = $FilePath }
    if ($ArgumentList) { $options.ArgumentList = $ArgumentList }
    $game = Get-PatriciaGame
    if (-not $game) {
        Start-Process @options
        Write-Output "Opened $FilePath."
        return
    }
    $screen = Get-PatriciaSafeScreen $game
    if (-not $screen) {
        throw "$($game.ProcessName) is running and there is no other screen, so nothing was opened."
    }
    $before = @{}
    Get-Process | Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
        ForEach-Object { $before[[int64]$_.MainWindowHandle] = $true }
    Start-Process @options -WindowStyle Minimized
    $deadline = (Get-Date).AddSeconds(15)
    $moved = 0
    while ((Get-Date) -lt $deadline -and $moved -eq 0) {
        Start-Sleep -Milliseconds 250
        Get-Process | Where-Object {
            $_.MainWindowHandle -ne [IntPtr]::Zero -and
            $_.Id -ne $game.Id -and
            -not $before.ContainsKey([int64]$_.MainWindowHandle)
        } | ForEach-Object {
            Move-PatriciaWindow $_.MainWindowHandle $screen
            $moved += 1
        }
    }
    if ($moved -gt 0) {
        Write-Output "Opened $FilePath on the screen $($screen.DeviceName), away from $($game.ProcessName)."
    } else {
        Write-Warning "Started $FilePath while $($game.ProcessName) was running, but no new window showed up to move. It may be minimized on the taskbar."
    }
}
"""

STEP_WRAPPER = r"""
try {
    $global:LASTEXITCODE = 0
__COMMAND__
    if ($global:LASTEXITCODE -ne 0) { exit $global:LASTEXITCODE }
} catch {
    [Console]::Error.WriteLine($_.ToString())
    exit 1
}
exit 0
"""


@dataclass
class StepResult:
    description: str
    command: str
    exit_code: int | None
    output: str
    error: str
    seconds: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def as_dict(self) -> dict:
        return {
            "description": self.description,
            "command": self.command,
            "exit_code": self.exit_code,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class RunReport:
    steps: list[StepResult] = field(default_factory=list)
    check: StepResult | None = None
    refused: str = ""

    @property
    def all_ok(self) -> bool:
        return not self.refused and all(step.ok for step in self.steps)


def is_windows() -> bool:
    return os.name == "nt"


def shell_path() -> str | None:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


def running_processes() -> set[str]:
    """Lowercase process names without .exe. Empty off Windows."""
    if not is_windows():
        return set()
    try:
        done = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return parse_tasklist(done.stdout)


def parse_tasklist(text: str) -> set[str]:
    names: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        name = row[0].strip().lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name:
            names.add(name)
    return names


def running_game(settings: Settings, names: set[str] | None = None) -> str | None:
    names = running_processes() if names is None else names
    for game in settings.quiet_games:
        if game.lower().removesuffix(".exe") in names:
            return game
    return None


def opens_without_helper(command: str) -> bool:
    """True when a command opens something without Open-Window."""
    for line in command.splitlines():
        text = line.split("#", 1)[0].lower()
        if "open-window" in text:
            continue
        if any(re.search(pattern, text) for pattern in _OPEN_PATTERNS):
            return True
    return False


def build_script(settings: Settings, command: str) -> str:
    games = ", ".join("'" + name.replace("'", "''") + "'" for name in settings.quiet_games)
    # Not indented, so here-strings in a command keep working.
    return PREAMBLE.replace("__GAMES__", games) + STEP_WRAPPER.replace("__COMMAND__", command)


def _clean_stderr(text: str) -> str:
    if not text.startswith("#< CLIXML"):
        return text
    parts = re.findall(r'<S S="Error">(.*?)</S>', text, flags=re.S)
    joined = "".join(parts).replace("_x000D__x000A_", "\n")
    return unescape(joined)


def _trim(text: str, limit: int = OUTPUT_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…(cut off)"


def run_step(settings: Settings, description: str, command: str) -> StepResult:
    started = time.monotonic()
    shell = shell_path()
    if shell is None:
        return StepResult(description, command, None, "", "PowerShell was not found on this PC.", 0.0)
    script = build_script(settings, command)
    handle, path = tempfile.mkstemp(prefix="patricia-", suffix=".ps1")
    try:
        # Windows PowerShell 5.1 needs the BOM to read UTF-8 scripts.
        with os.fdopen(handle, "w", encoding="utf-8-sig") as file:
            file.write(script)
        extra = {"creationflags": CREATE_NO_WINDOW} if is_windows() else {}
        try:
            done = subprocess.run(
                [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
                capture_output=True,
                timeout=settings.pc_timeout,
                stdin=subprocess.DEVNULL,
                **extra,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"").decode("utf-8", "replace")
            return StepResult(
                description,
                command,
                None,
                _trim(output),
                f"Stopped after {settings.pc_timeout} seconds.",
                time.monotonic() - started,
            )
        except OSError as exc:
            return StepResult(description, command, None, "", str(exc), time.monotonic() - started)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return StepResult(
        description,
        command,
        done.returncode,
        _trim(done.stdout.decode("utf-8", "replace")),
        _trim(_clean_stderr(done.stderr.decode("utf-8", "replace"))),
        time.monotonic() - started,
    )


def run_plan(settings: Settings, plan: dict) -> RunReport:
    report = RunReport()
    game = running_game(settings)
    if game:
        risky = [step for step in plan.get("commands", []) if opens_without_helper(step["command"])]
        if risky:
            report.refused = (
                f"{game} is running, and a step opens something without moving it off the game screen. "
                "Nothing was run."
            )
            return report
    for step in plan.get("commands", []):
        result = run_step(settings, step["description"], step["command"])
        report.steps.append(result)
        if not result.ok:
            break
    check = (plan.get("verify_command") or "").strip()
    if check:
        report.check = run_step(settings, "Check the result", check)
    return report


# ---------------------------------------------------------------- Claude ---

PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Hand back the PowerShell plan for Joeii to approve.",
    "input_schema": {
        "type": "object",
        "properties": {
            "possible": {
                "type": "boolean",
                "description": "False when commands cannot do this, or it would be unsafe.",
            },
            "reason": {
                "type": "string",
                "description": "When not possible: why, and what Joeii could do instead.",
            },
            "summary": {
                "type": "string",
                "description": "One or two plain sentences on what will happen.",
            },
            "commands": {
                "type": "array",
                "maxItems": MAX_STEPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "A few plain words."},
                        "command": {"type": "string", "description": "PowerShell to run."},
                    },
                    "required": ["description", "command"],
                },
            },
            "verify_command": {
                "type": "string",
                "description": "Read-only PowerShell that prints evidence the goal was reached.",
            },
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "needs_admin": {"type": "boolean"},
        },
        "required": ["possible", "summary", "commands", "verify_command", "risk", "needs_admin"],
    },
}

VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Say whether the goal was reached, and how to fix it if not.",
    "input_schema": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "summary": {"type": "string", "description": "One or two plain sentences for Joeii."},
            "problem": {"type": "string", "description": "When it failed: what went wrong, plainly."},
            "fix": {"type": "string", "description": "When it failed: how to fix it."},
            "fix_commands": {
                "type": "array",
                "maxItems": MAX_STEPS,
                "items": PLAN_TOOL["input_schema"]["properties"]["commands"]["items"],
                "description": "Commands that would fix it, if commands can. Leave empty otherwise.",
            },
            "fix_verify_command": {"type": "string"},
            "fix_risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "fix_needs_admin": {"type": "boolean"},
        },
        "required": ["success", "summary"],
    },
}


def _rules(settings: Settings, game: str | None) -> str:
    now = datetime.now(settings.timezone).strftime("%A, %B %d, %Y %I:%M %p %Z")
    if game:
        game_line = (
            f"{game} is running right now on Joeii's main screen. Do not open, show, or focus "
            "anything there. Open-Window puts new windows on the screen Discord is on."
        )
    else:
        game_line = (
            "No game is running right now, but always use Open-Window anyway, because a game "
            "could start before the plan runs."
        )
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return (
        "You plan PowerShell commands for Joeii's own Windows PC. Patricia shows him the exact "
        "commands, and they only run after he presses Yes.\n"
        f"PC: {platform.platform()}. User: {user}. Home: {os.path.expanduser('~')}. "
        f"Computer: {platform.node()}. Local time: {now}.\n"
        "Rules:\n"
        "- Each command runs in its own fresh, hidden PowerShell process with "
        "$ErrorActionPreference = 'Stop'. Variables do not carry over between commands, so "
        "each command must stand on its own.\n"
        "- It runs as Joeii's normal account, not as administrator. Nobody can answer prompts, "
        "UAC, or Read-Host. Use -Force or -Confirm:$false where a cmdlet would ask. If the "
        "task truly needs administrator, set needs_admin and say so in the summary.\n"
        f"- Each command must finish within {settings.pc_timeout} seconds. Use at most "
        f"{MAX_STEPS} commands, and as few as you can.\n"
        "- To open an app, file, folder, or website, always use "
        "Open-Window -FilePath '<path or url or app>' [-ArgumentList '<args>']. Never use "
        "Start-Process, start, ii, Invoke-Item, explorer, or anything else that opens a window. "
        "Open-Window already exists in every command.\n"
        f"- {game_line}\n"
        "- verify_command must only read. It prints what someone would look at to know the goal "
        "was reached, such as a setting's value, a file listing, or a running process.\n"
        "- Do only what was asked. Prefer reversible changes. Set risk to high for deleting "
        "data, changing system settings, installing or uninstalling software, or ending "
        "processes Joeii did not name. Never touch passwords, security tools, the bot's own "
        "folder, or its .env file.\n"
        "- If commands cannot do it (it needs clicking in an app, a physical action, or "
        "information you do not have), set possible to false and explain in reason."
    )


def _forced(settings: Settings, system: str, prompt: str, tool: dict) -> dict:
    from assistant.brain import structured

    return structured(settings, system, prompt, tool["name"], tool["description"], tool["input_schema"])


def normalize_steps(raw) -> list[dict]:
    steps: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", "")).strip()
        if not command:
            continue
        description = str(item.get("description", "")).strip() or "Step"
        steps.append({"description": description[:200], "command": command})
    return steps[:MAX_STEPS]


def plan_task(settings: Settings, goal: str) -> dict:
    game = running_game(settings)
    plan = _forced(settings, _rules(settings, game), f"Joeii wants this on his PC:\n{goal}", PLAN_TOOL)
    plan["commands"] = normalize_steps(plan.get("commands"))
    plan["verify_command"] = str(plan.get("verify_command") or "").strip()
    plan["possible"] = bool(plan.get("possible")) and bool(plan["commands"])
    plan["summary"] = str(plan.get("summary") or "").strip()
    plan["reason"] = str(plan.get("reason") or "").strip()
    plan["risk"] = plan.get("risk") if plan.get("risk") in ("low", "medium", "high") else "medium"
    plan["needs_admin"] = bool(plan.get("needs_admin"))
    plan["game"] = game or ""
    plan["goal"] = goal
    return plan


def judge(settings: Settings, plan: dict, report: RunReport) -> dict:
    game = running_game(settings)
    evidence = {
        "goal": plan.get("goal", ""),
        "steps_run": [step.as_dict() for step in report.steps],
        "steps_not_run": len(plan.get("commands", [])) - len(report.steps),
        "check": report.check.as_dict() if report.check else None,
    }
    prompt = (
        "Joeii approved these commands. Here is what happened, as JSON. Decide from the "
        "evidence whether his goal was reached. If it was not, say plainly what went wrong "
        "and how to fix it. When commands can fix it, give fix_commands that follow the same "
        "rules.\n\n" + json.dumps(evidence, indent=1)[:20000]
    )
    verdict = _forced(settings, _rules(settings, game), prompt, VERDICT_TOOL)
    verdict["success"] = bool(verdict.get("success"))
    verdict["fix_commands"] = normalize_steps(verdict.get("fix_commands"))
    return verdict


def fix_plan(plan: dict, verdict: dict) -> dict | None:
    steps = verdict.get("fix_commands") or []
    if verdict.get("success") or not steps:
        return None
    return {
        "possible": True,
        "goal": plan.get("goal", ""),
        "summary": str(verdict.get("fix") or "Try to fix what went wrong.").strip(),
        "commands": steps,
        "verify_command": str(verdict.get("fix_verify_command") or plan.get("verify_command") or ""),
        "risk": verdict.get("fix_risk") if verdict.get("fix_risk") in ("low", "medium", "high") else "medium",
        "needs_admin": bool(verdict.get("fix_needs_admin")),
        "game": plan.get("game", ""),
        "attempt": int(plan.get("attempt", 1)) + 1,
    }
