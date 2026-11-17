"""Patricia's Discord status: which mood fits right now, and the lines for each."""

from __future__ import annotations

from datetime import datetime

POOLS: dict[str, list[str]] = {
    "asleep": [
        "🌙 Watching over Joeii",
        "🧸 Here if you need me",
        "🕯️ Keeping the lights on",
    ],
    "bedtime": [
        "⏰ Watching the clock for you",
        "😴 Plotting your bedtime",
        "⚕️ Heroes never die… but they do sleep",
        "🕯️ Keeping the lights on",
    ],
    "overwatch": [
        "🎮 Spectating your Overwatch games",
        "💛 Healing from the backline",
        "🛡️ On payload duty",
        "🎧 Listening to your chaos",
    ],
    "morning": [
        "🫖 Keeping the kettle warm",
        "👀 Making sure you drink water",
        "✨ Tidying up the timeline",
        "💌 Holding your reminders",
    ],
    "day": [
        "📝 Taking notes, judging gently",
        "👀 Making sure you drink water",
        "🐾 Patrolling the house",
        "🍪 Guarding the cookie jar",
        "✨ Tidying up the timeline",
        "💌 Holding your reminders",
    ],
    "evening": [
        "🫖 Keeping the kettle warm",
        "🧸 Here if you need me",
        "🐾 Patrolling the house",
        "🍪 Guarding the cookie jar",
        "🕯️ Keeping the lights on",
    ],
}


def pick_mood(now: datetime, *, in_bedtime: bool, bedtime_done: bool, gaming: bool) -> str:
    """Bedtime wins over gaming: if he is still playing after 8:30, he hears about it."""
    if bedtime_done:
        return "asleep"
    if in_bedtime:
        return "bedtime"
    if gaming:
        return "overwatch"
    hour = now.hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "day"
    return "evening"


def next_line(mood: str, previous: str | None) -> str:
    """The next line in this mood's set, never the same one twice in a row."""
    pool = POOLS[mood]
    if previous in pool:
        return pool[(pool.index(previous) + 1) % len(pool)]
    return pool[0]
