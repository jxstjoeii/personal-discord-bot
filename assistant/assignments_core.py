"""Assignment tracker: the parts that do not need Discord."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from assistant.timeparse import parse_when

_HAS_TIME = re.compile(
    r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}:\d{2}\b|\bnoon\b|\bmidnight\b|\bin \d+ (minute|hour)",
    re.IGNORECASE,
)
EVENING = time(17, 0)
MORNING = time(8, 0)
LATE_GRACE = timedelta(hours=6)


def parse_due(text: str, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """Like parse_when, but a day with no time means 11:59 PM that day. Returns UTC."""
    moment = parse_when(text, tz, now)
    if _HAS_TIME.search(text):
        return moment
    local = moment.astimezone(tz)
    end_of_day = datetime.combine(local.date(), time(23, 59), tzinfo=tz)
    return end_of_day.astimezone(timezone.utc)


def checkpoints(due_utc: datetime, tz: ZoneInfo) -> list[tuple[str, datetime]]:
    """Reminder times for an assignment, in UTC, oldest first.

    3 days before and 1 day before at 5 PM, the morning of at 8 AM, and 2 hours
    before when it is due later in the day. Then one check after it is due.
    """
    due_local = due_utc.astimezone(tz)
    day = due_local.date()
    points = [
        ("3d", datetime.combine(day - timedelta(days=3), EVENING, tzinfo=tz)),
        ("1d", datetime.combine(day - timedelta(days=1), EVENING, tzinfo=tz)),
        ("morning", datetime.combine(day, MORNING, tzinfo=tz)),
        ("2h", due_local - timedelta(hours=2)),
        ("overdue", due_local + timedelta(minutes=30)),
    ]
    result = []
    for key, moment in points:
        if key not in ("overdue",) and moment >= due_local:
            continue
        if key == "2h" and due_local.time() < time(10, 0):
            continue  # The morning reminder already covers early deadlines.
        result.append((key, moment.astimezone(timezone.utc)))
    # Drop reminders that would land within an hour of the next one.
    cleaned: list[tuple[str, datetime]] = []
    for key, moment in result:
        if cleaned and key != "overdue" and moment - cleaned[-1][1] < timedelta(hours=1):
            cleaned[-1] = (key, moment)
            continue
        cleaned.append((key, moment))
    return cleaned


def pending(due_utc: datetime, tz: ZoneInfo, sent: list[str], now: datetime, created: datetime) -> str | None:
    """The one reminder to send now, if any. Old missed ones are skipped, not piled up."""
    ready = [
        (key, moment)
        for key, moment in checkpoints(due_utc, tz)
        if key not in sent and moment <= now and moment > created
    ]
    if not ready:
        return None
    key, moment = ready[-1]
    if key != "overdue" and now - moment > LATE_GRACE:
        return None
    return key


def message(key: str, title: str, course: str, when: str) -> str:
    name = f"**{title}**" + (f" ({course})" if course else "")
    texts = {
        "3d": f"📚 Heads up: {name} is due {when}, in 3 days. Good time to get started.",
        "1d": f"📚 {name} is due tomorrow, {when}. How's it coming along?",
        "morning": f"📚 Today's the day: {name} is due {when}. You've got this.",
        "2h": f"⏰ {name} is due in 2 hours, {when}. Final push!",
        "overdue": f"📚 {name} was due {when}. Did you turn it in? Tap ✅ if it's done.",
    }
    return texts[key]
