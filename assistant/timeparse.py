from __future__ import annotations

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
