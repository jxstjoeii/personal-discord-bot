"""Instant PC controls: volume, media keys, lock, screens off.

These are small, safe, easy-to-undo actions, so they run right away with no
Yes/No step. They press the same media keys a keyboard has, using Windows'
own functions from Python. Nothing is installed and no window opens.
"""

from __future__ import annotations

import re
import time

from assistant import pc

VK = {
    "mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "next_track": 0xB0,
    "previous_track": 0xB1,
    "play_pause": 0xB3,
}
STEP = 2            # Windows moves the volume 2% per key press.
ACTIONS = ["volume_up", "volume_down", "set_volume", "mute", "play_pause",
           "next_track", "previous_track", "lock", "screens_off"]


def _press(code: int, times: int = 1) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    for _ in range(max(1, times)):
        user32.keybd_event(code, 0, 0, 0)       # key down
        user32.keybd_event(code, 0, 2, 0)       # key up
        time.sleep(0.01)


def run(action: str, amount: int | None = None) -> str:
    """Does the action and returns a short reply."""
    if not pc.is_windows():
        return "PC controls only work on the Windows PC."
    action = (action or "").strip().lower()
    if action == "volume_up":
        step = amount or 10
        _press(VK["volume_up"], max(1, step // STEP))
        return f"🔊 Volume up {step}%."
    if action == "volume_down":
        step = amount or 10
        _press(VK["volume_down"], max(1, step // STEP))
        return f"🔉 Volume down {step}%."
    if action == "set_volume":
        level = max(0, min(100, int(amount if amount is not None else 50)))
        _press(VK["volume_down"], 50)              # all the way down...
        if level:
            _press(VK["volume_up"], round(level / STEP))   # ...then up to the level
        return f"🔊 Volume set to {level}%."
    if action == "mute":
        _press(VK["mute"])
        return "🔇 Toggled mute."
    if action in ("play_pause", "next_track", "previous_track"):
        _press(VK[action])
        return {"play_pause": "⏯️ Play/pause.", "next_track": "⏭️ Skipped.", "previous_track": "⏮️ Back one."}[action]
    if action == "lock":
        import ctypes

        ctypes.windll.user32.LockWorkStation()
        return "🔒 Locked the PC."
    if action == "screens_off":
        import ctypes

        # Same as the screens timing out. Moving the mouse wakes them.
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        return "🌙 Screens off. Move the mouse to wake them."
    return f"I don't know the PC control {action}."


_NUMBER = r"(\d{1,3})\s*(?:%|percent)?"
_QUICK = [
    (rf"^(?:set |turn )?(?:the )?volume (?:to|at) {_NUMBER}$", "set_volume"),
    (rf"^(?:turn (?:the )?)?volume up(?: by)? {_NUMBER}$", "volume_up"),
    (rf"^(?:turn (?:the )?)?volume down(?: by)? {_NUMBER}$", "volume_down"),
    (r"^(?:turn (?:it |the volume )?up|volume up|louder)$", "volume_up"),
    (r"^(?:turn (?:it |the volume )?down|volume down|quieter|softer)$", "volume_down"),
    (r"^(?:mute|unmute)(?: (?:the )?(?:pc|computer|sound|audio|volume))?$", "mute"),
    (r"^(?:pause|play|resume|unpause)(?: (?:the )?(?:music|song|video|it))?$", "play_pause"),
    (r"^(?:skip|next)(?: (?:the )?(?:song|track))?$|^next (?:song|track)$", "next_track"),
    (r"^(?:previous|last|go back)(?: (?:the )?(?:song|track))?$|^previous (?:song|track)$", "previous_track"),
    (r"^lock (?:my |the )?(?:pc|computer|screen)$", "lock"),
    (r"^(?:turn off (?:my |the )?(?:screens?|monitors?|displays?)|screens? off)$", "screens_off"),
]


def quick(text: str) -> tuple[str, int | None] | None:
    """Matches short, plain commands like 'volume down' or 'skip song'. None otherwise."""
    cleaned = re.sub(r"^\((?:said out loud|voice message)\)\s*", "", text.strip().lower())
    cleaned = re.sub(r"^(?:please|can you|could you|patricia)[,\s]+", "", cleaned)
    cleaned = re.sub(r"[\s,]*(?:please|thanks|thank you)$", "", cleaned)
    cleaned = cleaned.strip(" .!?")
    if len(cleaned.split()) > 7:
        return None
    for pattern, action in _QUICK:
        match = re.match(pattern, cleaned)
        if match:
            amount = int(match.group(1)) if match.groups() and match.group(1) else None
            return action, amount
    return None
