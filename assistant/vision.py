"""Patricia's eyes: preparing pictures for Claude, and glancing at the screen.

Screenshots are taken only when Joeii asks. They are made by a hidden
PowerShell process, shrunk, sent to Claude with that one message, and deleted
right away. Nothing is saved.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

from assistant import pc

MAX_SIDE = 1568            # Claude sees up to about this many pixels on the long side.
RAW_LIMIT = 3_700_000      # Without Pillow, larger pictures can't be shrunk, so they're skipped.
MAX_IMAGES = 4
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@dataclass
class Picture:
    data: bytes
    mime: str
    label: str = ""

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def prepare(data: bytes, mime: str, label: str = "") -> Picture | None:
    """Shrinks a picture so Claude can take it. None if it can't be used."""
    mime = (mime or "").split(";")[0].strip().lower()
    try:
        from PIL import Image
    except ImportError:
        if mime in IMAGE_TYPES and len(data) <= RAW_LIMIT:
            return Picture(data, mime, label)
        return None
    try:
        image = Image.open(io.BytesIO(data))
        image.seek(0)
        image.thumbnail((MAX_SIDE, MAX_SIDE))
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85)
        return Picture(out.getvalue(), "image/jpeg", label)
    except Exception:
        if mime in IMAGE_TYPES and len(data) <= RAW_LIMIT:
            return Picture(data, mime, label)
        return None


SCREEN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PatriciaDpi {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
'@
[PatriciaDpi]::SetProcessDPIAware() | Out-Null
$games = @(__GAMES__)
$includeGame = $__INCLUDE_GAME__
$maxSide = __MAX_SIDE__

function Get-ScreenName($names) {
    foreach ($name in $names) {
        $found = Get-Process -Name $name -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } | Select-Object -First 1
        if ($found) { return [System.Windows.Forms.Screen]::FromHandle($found.MainWindowHandle).DeviceName }
    }
    return $null
}

$gameScreen = Get-ScreenName $games
$discordScreen = Get-ScreenName @('Discord', 'DiscordPTB', 'DiscordCanary')
$codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$params = New-Object System.Drawing.Imaging.EncoderParameters 1
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), 80L
$out = @()
$index = 0
foreach ($screen in [System.Windows.Forms.Screen]::AllScreens) {
    $index++
    $isGame = ($gameScreen -ne $null) -and ($screen.DeviceName -eq $gameScreen)
    $entry = [ordered]@{
        index = $index; primary = $screen.Primary; game = $isGame
        discord = ($screen.DeviceName -eq $discordScreen); path = $null; skipped = $false
    }
    if ($isGame -and -not $includeGame) {
        $entry.skipped = $true
        $out += $entry
        continue
    }
    $bounds = $screen.Bounds
    $full = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($full)
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $scale = [Math]::Min(1.0, $maxSide / [Math]::Max($bounds.Width, $bounds.Height))
    $small = New-Object System.Drawing.Bitmap $full, ([int]($bounds.Width * $scale)), ([int]($bounds.Height * $scale))
    $path = Join-Path $env:TEMP ("patricia-screen-" + [guid]::NewGuid().ToString("N") + ".jpg")
    $small.Save($path, $codec, $params)
    $graphics.Dispose(); $full.Dispose(); $small.Dispose()
    $entry.path = $path
    $out += $entry
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""


def _screen_label(entry: dict) -> str:
    parts = [f"Screen {entry.get('index')}"]
    if entry.get("primary"):
        parts.append("main screen")
    if entry.get("discord"):
        parts.append("has Discord")
    if entry.get("game"):
        parts.append("game screen")
    return ", ".join(parts)


def choose(entries: list[dict], which: str) -> list[dict]:
    usable = [e for e in entries if e.get("path")]
    which = (which or "all").lower()
    if which == "discord":
        picked = [e for e in usable if e.get("discord")]
    elif which == "main":
        picked = [e for e in usable if e.get("primary")]
    else:
        picked = usable
    return picked or usable[:1]


def capture(settings, which: str = "all", include_game: bool = False, timeout: int = 40) -> tuple[list[Picture], str]:
    """Screenshots of the chosen screens, and a note for Claude."""
    shell = pc.shell_path()
    if not pc.is_windows() or shell is None:
        return [], "Screen capture only works on the Windows PC."
    games = ", ".join("'" + g.replace("'", "''") + "'" for g in settings.quiet_games) or "'none'"
    script = (
        SCREEN_SCRIPT.replace("__GAMES__", games)
        .replace("$__INCLUDE_GAME__", "$true" if include_game else "$false")
        .replace("__MAX_SIDE__", str(MAX_SIDE))
    )
    handle, path = tempfile.mkstemp(prefix="patricia-screen-", suffix=".ps1")
    entries: list[dict] = []
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig") as file:
            file.write(script)
        done = subprocess.run(
            [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            creationflags=pc.CREATE_NO_WINDOW,
        )
        text = done.stdout.decode("utf-8", "replace").strip()
        start = text.find("[")
        if done.returncode != 0 or start < 0:
            error = done.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = error[-1] if error else "no picture came back"
            return [], f"I couldn't take a screenshot ({reason[:200]}). The PC may be locked."
        entries = json.loads(text[start:])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return [], f"I couldn't take a screenshot: {exc}"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    pictures: list[Picture] = []
    try:
        for entry in choose(entries, which)[:MAX_IMAGES]:
            with open(entry["path"], "rb") as file:
                pictures.append(Picture(file.read(), "image/jpeg", _screen_label(entry)))
    finally:
        for entry in entries:
            if entry.get("path"):
                try:
                    os.remove(entry["path"])
                except OSError:
                    pass
    skipped = [e for e in entries if e.get("skipped")]
    note = "Screenshots of: " + "; ".join(p.label for p in pictures) + "."
    if skipped:
        note += " The game screen was left out on purpose while a game is running. Joeii can ask to include it."
    if not pictures:
        note = "No screen could be captured."
    return pictures, note
