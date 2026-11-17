"""Medication check-in: the parts that do not need Discord."""

from __future__ import annotations

from datetime import date, datetime, timedelta

FIRST = "💊 Good morning, Joeii! Time for {label}. Tap ✅ once you've taken them."
AGAIN = [
    "💊 Quick check: have you taken {label} yet?",
    "💊 Still waiting on {label}. Take them when you get a sec, then tap ✅.",
    "💊 Friendly nudge: {label}. Future you says thanks.",
]
LAST = "💊 Last reminder for today: {label}. Tap ✅ once they're in."


def med_label(settings, briefing_config: dict | None) -> str:
    """'your Happy Pills' from the morning briefing, MEDS_NAME, or a plain default."""
    if settings.meds_name:
        return settings.meds_name
    items = []
    if isinstance(briefing_config, dict):
        medication = briefing_config.get("medication")
        if isinstance(medication, dict) and isinstance(medication.get("items"), list):
            items = [item for item in medication["items"] if isinstance(item, dict)]
    morning = [item for item in items if str(item.get("when", "morning")).lower() == "morning"]
    names = []
    for item in morning:
        called = str(item.get("called") or "").strip()
        name = str(item.get("name") or "").strip()
        if called:
            names.append(called)
        elif name:
            names.append(name)
    if not names:
        return "your morning meds"
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return "your " + joined


def nudge_text(number: int, label: str, last: bool) -> str:
    if last and number > 1:
        return LAST.format(label=label)
    if number == 1:
        return FIRST.format(label=label)
    return AGAIN[(number - 2) % len(AGAIN)].format(label=label)


def due(now: datetime, row: dict | None, start: datetime, until: datetime) -> bool:
    """Whether a nudge should go out now."""
    row = row or {}
    if row.get("taken_at") or now < start or now >= until:
        return False
    next_at = row.get("next_at")
    if not next_at:
        return True
    return now >= datetime.fromisoformat(next_at)


def streak(days: set[str], today: date) -> int:
    """Days in a row taken, counting back from today."""
    count = 0
    day = today
    while day.isoformat() in days:
        count += 1
        day -= timedelta(days=1)
    return count


def taken_text(count: int) -> str:
    if count >= 2:
        return f"Logged! 💊 That's a {count}-day streak. Proud of you."
    return "Logged! 💊 Thanks for taking care of yourself."

