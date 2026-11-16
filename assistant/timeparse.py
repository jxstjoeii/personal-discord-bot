from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser


class PastTime(Exception):
    def __init__(self, when: datetime):
        self.when = when
        super().__init__("that time is in the past")


def parse_when(text: str, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """Return the requested moment in UTC."""
    raw = text.strip()
    if not raw:
        raise ValueError("empty time")
    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    current = current.astimezone(tz)
    parsed = dateparser.parse(
        raw,
        settings={
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": tz.key,
            "TO_TIMEZONE": tz.key,
            "RELATIVE_BASE": current.replace(tzinfo=None),
        },
    )
    if parsed is None:
        raise ValueError(f"not a time: {raw}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    local = parsed.astimezone(tz)
    if local.astimezone(timezone.utc) <= current.astimezone(timezone.utc) - timedelta(seconds=30):
        raise PastTime(local)
    return local.astimezone(timezone.utc)


_UNITS = {
    "m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1,
    "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
    "d": 1440, "day": 1440, "days": 1440, "daily": 1440,
    "w": 10080, "week": 10080, "weeks": 10080, "weekly": 10080,
}
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
          "fifteen": 15, "twenty": 20, "thirty": 30, "half": 0.5}
MIN_REPEAT = 1
MAX_REPEAT = 10080 * 8


def parse_every(text: str) -> int:
    """'30 minutes', 'every 2 hours', 'day', 'daily', 'half an hour' -> minutes."""
    raw = text.strip().lower().removeprefix("every").strip()
    if raw in ("hourly",):
        return 60
    raw = raw.replace("half an hour", "30 minutes").replace("half hour", "30 minutes")
    match = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*|([a-z]+)\s+)?([a-z]+)", raw)
    if not match:
        raise ValueError(f"not a repeat: {text}")
    number, word, unit = match.groups()
    amount_text = number or word
    if unit not in _UNITS:
        raise ValueError(f"not a repeat unit: {unit}")
    if amount_text is None:
        amount = 1.0
    elif amount_text in _WORDS:
        amount = float(_WORDS[amount_text])
    else:
        try:
            amount = float(amount_text)
        except ValueError as exc:
            raise ValueError(f"not a number: {amount_text}") from exc
    minutes = round(amount * _UNITS[unit])
    if not MIN_REPEAT <= minutes <= MAX_REPEAT:
        raise ValueError("repeat out of range")
    return minutes


def describe_every(minutes: int) -> str:
    for size, name in ((10080, "week"), (1440, "day"), (60, "hour")):
        if minutes % size == 0:
            count = minutes // size
            return f"every {name}" if count == 1 else f"every {count} {name}s"
    return "every minute" if minutes == 1 else f"every {minutes} minutes"


def next_due(due: datetime, minutes: int, tz: ZoneInfo, now: datetime) -> datetime:
    """The first repeat after now, in UTC. Whole days keep the same local clock time."""
    step = timedelta(minutes=minutes)
    if minutes % 1440 == 0:
        local = due.astimezone(tz)
        while True:
            # Adding to a local time keeps 9:00 at 9:00 across daylight saving.
            local = (local.replace(tzinfo=None) + step).replace(tzinfo=tz)
            if local.astimezone(timezone.utc) > now:
                return local.astimezone(timezone.utc)
    skipped = max(0, int((now - due) / step))
    candidate = due + step * (skipped + 1)
    while candidate <= now:
        candidate += step
    return candidate.astimezone(timezone.utc)
