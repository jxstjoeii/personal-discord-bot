"""Bedtime nudges: the parts that do not need Discord.

From BEDTIME_START (8:30 PM by default) Patricia nudges Joeii every
BEDTIME_EVERY minutes until he says he is going to bed, or until the night
ends at BEDTIME_END. If the PC is off, the bot is off, so the nudges stop.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta

log = logging.getLogger(__name__)

# Used when Claude can't be reached. They get firmer as the night goes on.
FALLBACK = [
    "It's time to start getting ready for bed, Joeii. Wrap up what you're doing and head that way.",
    "Gentle nudge, but I mean it: time to start winding down. Teeth, charger, lights.",
    "Joeii, it's getting late. Save what you're doing and start getting ready for bed now.",
    "I'm not letting this one go. Bed is the plan. Close things up and get moving.",
    "This is your sleep I'm looking out for. Put it down and go get ready for bed, please.",
    "Still here, still asking. You'll feel so much better tomorrow if you go now.",
]


def parse_clock(text: str) -> time:
    """'20:30', '8:30pm', '8:30 PM', '21' -> time."""
    raw = text.strip().lower().replace(" ", "").replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", raw)
    if not match:
        raise ValueError(f"not a clock time: {text}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    half = match.group(3)
    if half:
        if not 1 <= hour <= 12:
            raise ValueError("hour out of range")
        hour = hour % 12 + (12 if half == "pm" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time out of range")
    return time(hour, minute)


def night_window(now: datetime, start: time, end: time) -> tuple[date, datetime, datetime]:
    """The evening this moment belongs to, with that night's start and end.

    With a start of 20:30 and an end of 04:00, 1 AM on Tuesday belongs to
    Monday night.
    """
    tz = now.tzinfo
    crosses_midnight = end <= start
    night = now.date()
    if crosses_midnight and now.time() < end:
        night -= timedelta(days=1)
    start_at = datetime.combine(night, start, tzinfo=tz)
    end_day = night + timedelta(days=1) if crosses_midnight else night
    end_at = datetime.combine(end_day, end, tzinfo=tz)
    return night, start_at, end_at


def current_slot(now: datetime, start_at: datetime, end_at: datetime, every_minutes: int) -> int | None:
    """0 for the first nudge, 1 for the next, and so on. None outside the window."""
    if not start_at <= now < end_at:
        return None
    return int((now - start_at) / timedelta(minutes=every_minutes))


def clock_text(moment: datetime | time) -> str:
    hour = moment.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{moment.strftime('%M %p')}"


def write_nudge(settings, number: int, now: datetime, earlier: list[str]) -> str:
    """A fresh, firm but kind nudge. Falls back to a fixed one if Claude is unavailable."""
    fallback = FALLBACK[min(number - 1, len(FALLBACK) - 1)]
    try:
        from assistant.brain import agent

        system = (
            "You are Patricia, Joeii's private assistant. You write his bedtime nudges. "
            "Be firm but kind: warm and caring, never guilt-tripping, sarcastic, or preachy, "
            "but clear that it is time. No 'maybe' or 'if you want'. Get a little firmer with "
            "each nudge while staying kind. Write one or two short sentences, with at most one "
            "emoji. Include one concrete next step, like saving the game, brushing teeth, "
            "putting the phone on the charger, or dimming the lights. Reply with only the message."
        )
        prompt = (
            f"Nudge number {number} tonight. It is {clock_text(now)}. He asked to start getting "
            f"ready for bed at {clock_text(settings.bedtime_start)}.\n"
        )
        if earlier:
            prompt += "Do not repeat these earlier nudges:\n" + "\n".join(f"- {line}" for line in earlier[-4:])
        text = agent(settings, system, prompt, [], lambda name, args: "", max_turns=1).strip()
        text = text.strip('"').strip()
        if text and len(text) <= 400:
            return text
    except Exception as exc:
        log.warning("Writing a bedtime nudge failed, so a fixed one is used: %s", exc)
    return fallback
