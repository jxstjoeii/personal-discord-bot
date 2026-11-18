"""Alarm helpers that don't need Discord: the beep sound, ringing rules, and wording.

An alarm "calls" Joeii: when it goes off, Patricia DMs him every RING_EVERY with
Stop and Snooze buttons, and beeps out of the PC speakers, until he taps Stop.
"""

from __future__ import annotations

import logging
import math
import struct
import sys
import wave
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

RING_EVERY = timedelta(seconds=30)
MAX_RINGS = 20  # 20 rings, 30 seconds apart: she gives up after about 10 minutes
SNOOZE = timedelta(minutes=5)

RATE = 22050


def beep_wav(path: Path) -> Path:
    """Write a short alarm pattern (beep beep beep, pause) as a WAV file. It loops."""
    frames = bytearray()

    def tone(seconds: float, pitch: float) -> None:
        count = int(RATE * seconds)
        fade = int(RATE * 0.01)
        for i in range(count):
            edge = min(1.0, i / fade, (count - i) / fade)
            sample = 0.6 * edge * math.sin(2 * math.pi * pitch * i / RATE)
            frames.extend(struct.pack("<h", int(sample * 32767)))

    def silence(seconds: float) -> None:
        frames.extend(b"\x00\x00" * int(RATE * seconds))

    for _ in range(3):
        tone(0.15, 1046.5)
        silence(0.08)
    silence(0.5)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(bytes(frames))
    return path


def start_beeping(path: Path) -> bool:
    """Loop the alarm sound on the PC speakers in the background. No window opens."""
    if sys.platform != "win32":
        return False
    try:
        import winsound

        if not path.exists():
            beep_wav(path)
        winsound.PlaySound(
            str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
        )
        return True
    except Exception:
        log.exception("Could not play the alarm sound")
        return False


def stop_beeping() -> None:
    if sys.platform != "win32":
        return
    try:
        import winsound

        winsound.PlaySound(None, 0)  # stops the looping sound
    except Exception:
        log.exception("Could not stop the alarm sound")


def alarm_rollover(passed: datetime, now: datetime) -> datetime | None:
    """A clock time that already passed today rolls to the same time tomorrow."""
    if now - passed > timedelta(hours=24):
        return None
    return (passed + timedelta(days=1)).astimezone(now.tzinfo)


def should_ring(row: dict, now: datetime) -> bool:
    """Whether a ringing alarm is due for its next DM."""
    nxt = row.get("next_ring_at")
    return not nxt or datetime.fromisoformat(nxt) <= now


def gave_up(row: dict) -> bool:
    return int(row.get("rings") or 0) >= MAX_RINGS


def ring_text(row: dict) -> str:
    label = (row.get("label") or "").strip() or "Alarm"
    rings = int(row.get("rings") or 0)
    if rings == 0:
        return f"⏰ **{label}**\nRinging! Tap Stop when you're up."
    return f"⏰ **{label}** (ring {rings + 1})\nStill ringing. Tap Stop when you're up."


def gave_up_text(row: dict) -> str:
    label = (row.get("label") or "").strip() or "your alarm"
    minutes = int(MAX_RINGS * RING_EVERY.total_seconds() // 60)
    return f"I rang for {label} for {minutes} minutes and you didn't answer, so I stopped."
