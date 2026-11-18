"""Patricia's eyes: preparing pictures for Claude, and glancing at the screen.

Screenshots are taken only when Joeii asks, inside this Python process with
Pillow's ImageGrab. They are shrunk, sent to Claude with that one message, and
never written to disk.
"""

from __future__ import annotations

import base64
import csv
import io
import subprocess
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


def _process_ids(names: list[str]) -> set[int]:
    """Process ids for these program names (without .exe), from tasklist."""
    wanted = {n.lower().removesuffix(".exe") for n in names}
    try:
        done = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=pc.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    ids = set()
    for row in csv.reader(io.StringIO(done.stdout)):
        if len(row) >= 2 and row[0].lower().removesuffix(".exe") in wanted:
            try:
                ids.add(int(row[1]))
            except ValueError:
                pass
    return ids


def _monitors() -> list[dict]:
    """Each monitor's rectangle in desktop coordinates, using Windows' own monitor list."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        # Real pixel sizes on scaled (125%, 150%) displays.
        user32.SetProcessDPIAware()
    except Exception:
        pass

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    found: list[dict] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def collect(handle, _dc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            r = info.rcMonitor
            found.append({"handle": int(handle or 0), "box": (r.left, r.top, r.right, r.bottom),
                          "primary": bool(info.dwFlags & 1)})
        return 1

    user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
    return found


def _monitor_of(names: list[str]) -> int | None:
    """The monitor showing a visible window of one of these programs."""
    import ctypes
    from ctypes import wintypes

    ids = _process_ids(names)
    if not ids:
        return None
    user32 = ctypes.windll.user32
    hit: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def check(hwnd, _data):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in ids:
            hit.append(int(user32.MonitorFromWindow(hwnd, 2) or 0))  # 2: nearest monitor
            return False
        return True

    user32.EnumWindows(callback_type(check), 0)
    return hit[0] if hit else None


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


def capture(settings, which: str = "all", include_game: bool = False) -> tuple[list[Picture], str]:
    """Screenshots of the chosen screens, and a note for Claude. Nothing is saved to disk."""
    if not pc.is_windows():
        return [], "Screen capture only works on the Windows PC."
    try:
        from PIL import ImageGrab
    except ImportError:
        return [], "Screen capture needs Pillow. Run restart.ps1 in Patricia's folder to install it."
    try:
        monitors = _monitors()
        game_monitor = _monitor_of(list(settings.quiet_games))
        discord_monitor = _monitor_of(["Discord", "DiscordPTB", "DiscordCanary"])
    except Exception as exc:
        return [], f"I couldn't find the screens: {exc}"
    entries = []
    for index, monitor in enumerate(monitors, start=1):
        is_game = game_monitor is not None and monitor["handle"] == game_monitor
        entries.append({
            "index": index,
            "primary": monitor["primary"],
            "game": is_game,
            "discord": discord_monitor is not None and monitor["handle"] == discord_monitor,
            "box": monitor["box"],
            "path": None if (is_game and not include_game) else "screen",
            "skipped": is_game and not include_game,
        })
    pictures: list[Picture] = []
    try:
        for entry in choose(entries, which)[:MAX_IMAGES]:
            shot = ImageGrab.grab(bbox=entry["box"], all_screens=True)
            out = io.BytesIO()
            shot.convert("RGB").save(out, format="JPEG", quality=85)
            picture = prepare(out.getvalue(), "image/jpeg", _screen_label(entry))
            if picture is not None:
                pictures.append(picture)
    except OSError as exc:
        return [], f"I couldn't take a screenshot ({exc}). The PC may be locked or the screen asleep."
    skipped = [e for e in entries if e.get("skipped")]
    if not pictures:
        return [], "No screen could be captured."
    note = "Screenshots of: " + "; ".join(p.label for p in pictures) + "."
    if skipped:
        note += " The game screen was left out on purpose while a game is running. Joeii can ask to include it."
    return pictures, note
