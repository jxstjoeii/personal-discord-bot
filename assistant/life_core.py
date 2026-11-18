"""Mood check-ins and birthdays: the parts that do not need Discord."""

from __future__ import annotations

import calendar
import re
from datetime import date

# ------------------------------------------------------------------ mood --

MOOD_FACES = {1: "😞", 2: "🙁", 3: "😐", 4: "🙂", 5: "😄"}
MOOD_REPLIES = {
    1: "I'm sorry today was rough. 💜 Want to tell me what happened? I'm here to listen.",
    2: "Thanks for telling me. Not every day is a good one, and tomorrow's a fresh start. Want to talk about it?",
    3: "A so-so day. Is there one small thing that would make tomorrow a little better?",
    4: "Glad it was a good one! 🙂",
    5: "Yay, a great day! 😄 What made it so good?",
}
HARD_STRETCH = (
    "You've had a few hard days in a row. That's a lot to carry. Talking to someone you trust "
    "can really help, and I'm always here too. 💜"
)


def mood_reply(score: int, recent: list[int]) -> str:
    """recent: scores from the last few days, newest last, including today."""
    text = MOOD_REPLIES[max(1, min(5, int(score)))]
    if len(recent) >= 3 and all(s <= 2 for s in recent[-3:]):
        text += "\n" + HARD_STRETCH
    return text


def mood_summary(rows: list[dict]) -> str:
    if not rows:
        return ""
    scores = [int(r["score"]) for r in rows if r.get("score")]
    if not scores:
        return ""
    average = sum(scores) / len(scores)
    faces = " ".join(MOOD_FACES[s] for s in scores)
    return f"{faces} (average {average:.1f} out of 5)"


# ------------------------------------------------------------- birthdays --

_MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9


def parse_birthday(text: str) -> tuple[int, int, int | None]:
    """'March 3', '3 March 2004', 'mar 3rd', '3/3', '03/03/2004' -> (month, day, year or None)."""
    raw = text.strip().lower().replace(",", " ")
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw)
    month = day = year = None
    numeric = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", raw)
    if numeric:
        month, day = int(numeric.group(1)), int(numeric.group(2))
        if numeric.group(3):
            year = int(numeric.group(3))
            year += 2000 if year < 100 and year <= date.today().year % 100 else (1900 if year < 100 else 0)
    else:
        words = raw.split()
        for word in words:
            if word in _MONTHS and month is None:
                month = _MONTHS[word]
            elif word.isdigit() and len(word) == 4:
                year = int(word)
            elif word.isdigit() and day is None:
                day = int(word)
    if not month or not day:
        raise ValueError(f"not a birthday: {text}")
    if not 1 <= month <= 12 or not 1 <= day <= (29 if month == 2 else calendar.monthrange(2001, month)[1]):
        raise ValueError(f"not a real date: {text}")
    if year is not None and not 1900 <= year <= date.today().year:
        year = None
    return month, day, year


def next_birthday(month: int, day: int, today: date) -> date:
    """The next time this birthday comes around, today included. Feb 29 is Feb 28 in other years."""
    for year in (today.year, today.year + 1):
        actual = day
        if month == 2 and day == 29 and not calendar.isleap(year):
            actual = 28
        candidate = date(year, month, actual)
        if candidate >= today:
            return candidate
    raise AssertionError("unreachable")


def birthday_line(row: dict, today: date) -> str:
    when = next_birthday(int(row["month"]), int(row["day"]), today)
    days = (when - today).days
    turning = f", turning {when.year - int(row['year'])}" if row.get("year") else ""
    if days == 0:
        label = "today"
    elif days == 1:
        label = "tomorrow"
    else:
        label = f"in {days} days ({when.strftime('%a, %b')} {when.day})"
    return f"{row['name']}: {label}{turning}"


def upcoming_birthdays(rows: list[dict], today: date, within_days: int) -> list[dict]:
    soon = []
    for row in rows:
        when = next_birthday(int(row["month"]), int(row["day"]), today)
        if (when - today).days <= within_days:
            soon.append({**row, "_when": when})
    return sorted(soon, key=lambda r: r["_when"])


def birthday_message(row: dict, today: date, days_before: int) -> str:
    when = next_birthday(int(row["month"]), int(row["day"]), today)
    turning = f" They're turning {when.year - int(row['year'])}." if row.get("year") else ""
    note = f" ({row['note']})" if row.get("note") else ""
    if days_before == 0:
        return f"🎂 Today is **{row['name']}**'s birthday!{turning}{note} Don't forget to wish them a happy birthday. 🎉"
    return (
        f"🎁 Heads up: **{row['name']}**'s birthday is in {days_before} days, on "
        f"{when.strftime('%A, %B')} {when.day}.{turning}{note} Time to think about a card or gift?"
    )
