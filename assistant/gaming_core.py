"""Gaming sessions: the parts that do not need Discord."""

from __future__ import annotations

from datetime import datetime, timedelta

MIN_SESSION_MINUTES = 10   # Shorter sessions (a quick launch to patch) get no wrap-up.
MISSES_TO_END = 2          # Checks in a row without the game before a session counts as over.


def duration_text(minutes: float) -> str:
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours}h {rest}m"
    if hours:
        return f"{hours}h"
    return f"{rest}m"


def clock(moment: datetime) -> str:
    hour = moment.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{moment.strftime('%M %p')}"


def minutes_between(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 60)


def week_start(now_local: datetime) -> datetime:
    """Monday 00:00 of this week, local time."""
    monday = now_local.date() - timedelta(days=now_local.weekday())
    return datetime.combine(monday, datetime.min.time(), tzinfo=now_local.tzinfo)


def total_minutes(sessions: list[dict], since: datetime, now: datetime) -> float:
    """Minutes played since a moment, counting only the part of each session after it."""
    total = 0.0
    for row in sessions:
        start = datetime.fromisoformat(row["started_at"])
        end = datetime.fromisoformat(row["ended_at"] or row["last_seen_at"] or row["started_at"])
        if row["ended_at"] is None:
            end = max(end, now)
        start = max(start, since)
        if end > start:
            total += minutes_between(start, end)
    return total


def wrap_up(game: str, start_local: datetime, end_local: datetime, week_minutes: float,
            bedtime: bool, promise: str | None) -> str:
    played = minutes_between(start_local, end_local)
    lines = [
        f"🎮 GG! You played **{game}** for **{duration_text(played)}** "
        f"({clock(start_local)} to {clock(end_local)})."
    ]
    lines.append(f"That's {duration_text(week_minutes)} this week.")
    if promise == "kept":
        lines.append("And you kept your one-more-game promise. Proud of you! 🎉")
    elif promise == "late":
        lines.append("That one more game ran a little long, but you got there. 😄")
    if bedtime:
        lines.append("It's bedtime territory now, so this is the perfect moment to start winding down. 🌙")
    elif played >= 180:
        lines.append("Long session! Maybe grab some water and stretch. 💧")
    return "\n".join(lines)


def one_more_text(game: str, overtime: bool) -> str:
    if overtime:
        return f"⏰ Still in {game}? That was supposed to be the last one. Time to wrap it up, Joeii."
    return "⏰ That was your one more game! Finish this match and call it there. 🎮"
