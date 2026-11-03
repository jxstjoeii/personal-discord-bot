from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

PAGE_SIZE = 6


def one_tag(value: str) -> str:
    return "-".join(value.strip().lower().split())


def normalize_tags(tags: str) -> str:
    seen: list[str] = []
    for part in tags.split(","):
        tag = one_tag(part)
        if tag and tag not in seen:
            seen.append(tag)
    return ", ".join(seen)


def format_when(moment: datetime, timezone: ZoneInfo) -> str:
    local = moment.astimezone(timezone)
    return local.strftime("%a, %b %d, %Y %I:%M %p %Z")


def format_stored(value: str, timezone: ZoneInfo) -> str:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        from datetime import timezone as utc

        moment = moment.replace(tzinfo=utc)
    return format_when(moment, timezone)


def page_slice(items: list, page: int, page_size: int = PAGE_SIZE) -> tuple[list, int, int]:
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    current = min(max(page, 1), total_pages)
    start = (current - 1) * page_size
    return items[start : start + page_size], current, total_pages


def note_summary(note: dict) -> str:
    tags = f" · {note['tags']}" if note["tags"] else ""
    preview = " ".join(str(note["body"]).split())
    if len(preview) > 90:
        preview = preview[:87] + "..."
    title = " ".join(str(note["title"]).split())
    return f"**#{note['id']} {title}**{tags}\n{preview}"


def split_discord(text: str, limit: int = 1900) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return ["I don't have a reply for that."]
    parts: list[str] = []
    remaining = cleaned
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    return [part for part in parts if part]


def note_problem(title: str, body: str) -> str | None:
    if not title.strip():
        return "A note needs a title."
    if len(title.strip()) > 120:
        return "Keep the title under 120 characters."
    if not body.strip():
        return "A note needs some text."
    if len(body) > 4000:
        return "That note is too long. Keep it under 4000 characters."
    return None


def reminder_problem(text: str) -> str | None:
    if not text.strip():
        return "Tell me what to remind you about."
    if len(text.strip()) > 500:
        return "Keep the reminder under 500 characters."
    return None
