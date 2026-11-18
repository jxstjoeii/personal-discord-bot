"""Nightly and weekly recaps: gathering the facts and writing them up."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from assistant.formatting import format_stored
from assistant.gaming_core import duration_text, minutes_between, total_minutes, week_start
from assistant.life_core import birthday_line, mood_summary, upcoming_birthdays
from assistant.meds_core import streak

log = logging.getLogger(__name__)


def _utc(local: datetime) -> datetime:
    return local.astimezone(timezone.utc)


def day_facts(db, owner: int, tz, now: datetime, extras: dict | None = None) -> dict:
    """What happened today and what's coming tomorrow. now is local time."""
    today = now.date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    tomorrow_start = start + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)
    done = [r["title"] for r in db.assignments_done_since(_utc(start))]
    due_tomorrow, due_soon = [], []
    for row in db.list_assignments(owner):
        due = datetime.fromisoformat(row["due_at"])
        if due < _utc(tomorrow_end):
            due_tomorrow.append(f"{row['title']} ({format_stored(row['due_at'], tz)})")
        elif due < _utc(start + timedelta(days=4)):
            due_soon.append(f"{row['title']} ({format_stored(row['due_at'], tz)})")
    reminders = [
        f"{format_stored(r['due_at'], tz)}: {r['text']}"
        for r in db.list_reminders(owner)
        if _utc(tomorrow_start) <= datetime.fromisoformat(r["due_at"]) < _utc(tomorrow_end)
    ]
    meds_row = db.get_meds(today.isoformat()) or {}
    taken = set(db.meds_taken_days())
    played = total_minutes(db.game_sessions_since(_utc(start) - timedelta(days=1)), _utc(start), _utc(now))
    mood = db.get_mood(today.isoformat())
    birthdays = [birthday_line(r, today) for r in upcoming_birthdays(db.list_birthdays(), today, 7)]
    facts = {
        "date": now.strftime("%A, %B %d"),
        "done": done,
        "due_tomorrow": due_tomorrow,
        "due_soon": due_soon,
        "reminders_tomorrow": reminders,
        "meds": ("taken" if meds_row.get("taken_at") else "not logged") + f", streak {streak(taken, today)} day(s)",
        "played": duration_text(played) if played >= 1 else "",
        "mood": f"{mood['score']}/5" + (f" ({mood['note']})" if mood.get("note") else "") if mood else "",
        "birthdays": birthdays,
    }
    facts.update(extras or {})
    return facts


def week_facts(db, owner: int, tz, now: datetime) -> dict:
    """Monday to now, plus what's coming in the next week."""
    start = week_start(now)
    today = now.date()
    sessions = db.game_sessions_since(_utc(start) - timedelta(days=1))
    played = total_minutes(sessions, _utc(start), _utc(now))
    finished = [
        minutes_between(datetime.fromisoformat(r["started_at"]), datetime.fromisoformat(r["ended_at"]))
        for r in sessions
        if r["ended_at"] and datetime.fromisoformat(r["started_at"]) >= _utc(start)
    ]
    taken = set(db.meds_taken_days())
    days_so_far = (today - start.date()).days + 1
    meds_days = sum(1 for i in range(days_so_far) if (start.date() + timedelta(days=i)).isoformat() in taken)
    moods = db.moods_since(start.date().isoformat())
    due_next = [
        f"{r['title']} ({format_stored(r['due_at'], tz)})"
        for r in db.list_assignments(owner)
        if datetime.fromisoformat(r["due_at"]) < _utc(now + timedelta(days=8))
    ]
    return {
        "range": f"{start.strftime('%b %d')} to {now.strftime('%b %d')}",
        "played": duration_text(played) if played >= 1 else "none",
        "sessions": len(finished),
        "longest": duration_text(max(finished)) if finished else "",
        "done": [r["title"] for r in db.assignments_done_since(_utc(start))],
        "due_next_week": due_next,
        "meds": f"{meds_days} of {days_so_far} days, current streak {streak(taken, today)}",
        "moods": mood_summary(moods),
        "mood_notes": [f"{r['day']}: {r['note']}" for r in moods if r.get("note")],
        "birthdays": [birthday_line(r, today) for r in upcoming_birthdays(db.list_birthdays(), today, 14)],
    }


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "none"


def fallback_day(f: dict) -> str:
    parts = [f"🌙 **Today, {f['date']}**"]
    if f["done"]:
        parts.append("✅ Finished: " + ", ".join(f["done"]))
    parts.append(f"💊 Meds: {f['meds']}")
    if f["played"]:
        parts.append(f"🎮 Played: {f['played']}")
    if f["mood"]:
        parts.append(f"💭 Mood: {f['mood']}")
    if f["due_tomorrow"] or f["reminders_tomorrow"]:
        parts.append("📅 Tomorrow: " + "; ".join(f["due_tomorrow"] + f["reminders_tomorrow"]))
    if f["birthdays"]:
        parts.append("🎂 " + "; ".join(f["birthdays"]))
    parts.append("Good night, Joeii. 💜")
    return "\n".join(parts)


def fallback_week(f: dict) -> str:
    parts = [f"📆 **Your week, {f['range']}**"]
    if f["done"]:
        parts.append(f"✅ Finished {len(f['done'])}: " + ", ".join(f["done"]))
    parts.append(f"💊 Meds: {f['meds']}")
    parts.append(f"🎮 Played: {f['played']}" + (f" (longest {f['longest']})" if f["longest"] else ""))
    if f["moods"]:
        parts.append(f"💭 Mood: {f['moods']}")
    if f["due_next_week"]:
        parts.append("📚 Coming up: " + "; ".join(f["due_next_week"]))
    if f["birthdays"]:
        parts.append("🎂 " + "; ".join(f["birthdays"]))
    return "\n".join(parts)


def write(settings, kind: str, facts: dict, about: str) -> str:
    fallback = fallback_day(facts) if kind == "day" else fallback_week(facts)
    try:
        from assistant.brain import agent

        if kind == "day":
            task = (
                "Write Joeii's nightly recap for Discord, under 900 characters. Open with one warm line "
                "about his day, then: what he got done (celebrate it), meds, play time and mood if there "
                "are any, then a short 'tomorrow' section with what's due, reminders, weather, and "
                "calendar. Mention upcoming birthdays. End with a kind good night. If his mood was low, "
                "be gentle and supportive, never preachy."
            )
        else:
            task = (
                "Write Joeii's weekly look back for Discord, under 1400 characters. Celebrate wins first, "
                "then meds consistency, gaming time, and mood across the week (notice patterns kindly, "
                "no guilt), then what's coming next week and upcoming birthdays. End with one small, "
                "doable suggestion for the week ahead and an encouraging line."
            )
        system = (
            "You are Patricia, Joeii's warm, slightly playful assistant. Use a few emoji and short bold "
            "labels so it's easy to skim. Use only the facts given; don't invent events. Skip sections "
            "that are empty. Reply with only the message."
        )
        body = "\n".join(
            (f"{key}:\n{_lines(value)}" if value else f"{key}: none") if isinstance(value, list)
            else f"{key}: {value or 'none'}"
            for key, value in facts.items()
        )
        text = agent(settings, system, f"{task}\n\nFacts:\n{body}\n\nWhat you know about Joeii:\n{about}",
                     [], lambda name, args: "", max_turns=1).strip()
        if text and len(text) <= 1900:
            return text
    except Exception as exc:
        log.warning("Writing the %s recap failed, so a plain one is used: %s", kind, exc)
    return fallback
