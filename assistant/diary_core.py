"""Diary: the parts that do not need Discord. Entries live in data/assistant.db, never in the repo."""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from assistant.life_core import parse_birthday

# Short questions that help put a name on a feeling. One or two at a time is plenty.
PROMPTS = (
    "What's one word for how you feel right now?",
    "What was the best part of today?",
    "What was the hardest part of today?",
    "What made you smile today?",
    "Did anything stress you out? What was it?",
    "Is your body tired, wired, or okay?",
    "Who did you enjoy talking to today?",
    "What's something you're proud of today, even a small thing?",
    "Is anything bugging you that you haven't said out loud?",
    "What are you looking forward to tomorrow?",
    "If today was weather, what kind would it be?",
    "What do you need more of right now: rest, fun, people, or quiet?",
)

# Feeling words to pick from when "how do you feel" is too big a question.
FEELINGS = (
    "happy", "proud", "calm", "excited", "grateful", "hopeful",
    "tired", "bored", "stressed", "anxious", "frustrated", "sad",
    "lonely", "annoyed", "overwhelmed", "relieved", "content", "meh",
)

MAX_ENTRY = 4000
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def prompts_for(day: str, count: int = 3) -> list[str]:
    """The same few prompts all day, different ones tomorrow."""
    picker = random.Random(f"diary-{day}")
    return picker.sample(PROMPTS, k=max(1, min(count, len(PROMPTS))))


def prompt_card(day: str, count: int = 3) -> str:
    lines = ["📓 A few questions, if you want them. Answer one, or just tell me about your day:"]
    lines += [f"• {question}" for question in prompts_for(day, count)]
    lines.append("Stuck on a word? Maybe: " + ", ".join(random.Random(f"feel-{day}").sample(FEELINGS, k=6)) + ".")
    return "\n".join(lines)


def clean_entry(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", (text or "").strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_ENTRY]


def parse_day(text: str, today: date) -> date:
    """'today', 'yesterday', 'monday', '3 days ago', '2026-11-20', '11/20', 'nov 20' -> a date, never in the future."""
    raw = (text or "").strip().lower().rstrip(".")
    if raw in ("", "today", "tonight"):
        return today
    if raw in ("yesterday", "last night"):
        return today - timedelta(days=1)
    ago = re.fullmatch(r"(\d{1,3}) days? ago", raw)
    if ago:
        return today - timedelta(days=int(ago.group(1)))
    weekday = raw.removeprefix("last ").strip()
    if weekday in _WEEKDAYS:
        back = (today.weekday() - _WEEKDAYS.index(weekday)) % 7
        return today - timedelta(days=back or 7)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    month, day, year = parse_birthday(raw)  # raises ValueError when it can't read it
    if year is not None:
        return date(year, month, day)
    guess = date(today.year, month, day) if not (month == 2 and day == 29) else date(today.year, 3, 1)
    if guess > today:
        guess = guess.replace(year=today.year - 1)
    return guess


def day_label(day: str) -> str:
    return date.fromisoformat(day).strftime("%A, %b %d, %Y").replace(" 0", " ")


def entry_time(row: dict, timezone: ZoneInfo) -> str:
    moment = datetime.fromisoformat(row["at"]).astimezone(timezone)
    return moment.strftime("%I:%M %p").lstrip("0")


def format_entries(rows: list[dict], timezone: ZoneInfo, *, show_ids: bool = True) -> str:
    """Entries grouped by day, oldest first."""
    if not rows:
        return ""
    out: list[str] = []
    current = None
    for row in rows:
        if row["day"] != current:
            current = row["day"]
            if out:
                out.append("")
            out.append(f"📓 **{day_label(current)}**")
        tag = f" (#{row['id']})" if show_ids else ""
        if row.get("prompt"):
            out.append(f"*{row['prompt']}*")
        out.append(f"{entry_time(row, timezone)}{tag}: {row['text']}")
    return "\n".join(out)
