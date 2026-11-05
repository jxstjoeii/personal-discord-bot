from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_UTC = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$")
_FLOATING = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$")
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?")
_BYDAY_PREFIX = re.compile(r"^[+-]?\d")
_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    all_day: bool
    spoken: str
    minutes: int


@dataclass(frozen=True)
class _Stamp:
    at: datetime
    all_day: bool


def events_from_ics(text: str, day: date, zone: ZoneInfo) -> list[CalendarEvent]:
    if not text:
        return []
    events: list[CalendarEvent] = []
    current: dict[str, list[tuple[str, dict[str, str]]]] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                event = _event_on_day(current, day, zone)
                if event is not None:
                    events.append(event)
            current = None
            continue
        if current is None:
            continue
        prop = _property(line)
        if prop is None:
            continue
        name, value, params = prop
        current.setdefault(name, []).append((value, params))
    return events


def events_from_local(data: object, day: date) -> list[CalendarEvent]:
    if not isinstance(data, dict):
        return []
    raw = data.get("events")
    if not isinstance(raw, list):
        return []
    weekday = day.strftime("%A")
    found: list[CalendarEvent] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        date_text = str(item.get("date") or "")
        names = item.get("weekdays")
        week_match = False
        if isinstance(names, list):
            week_match = any(str(name) == weekday for name in names)
        elif isinstance(names, str):
            week_match = names == weekday
        if date_text != day.isoformat() and not week_match:
            continue
        event = _make_event(
            title,
            bool(item.get("allDay")),
            str(item.get("time") or ""),
        )
        if event is not None:
            found.append(event)
    return found


def merge_events(groups: list[list[CalendarEvent]]) -> list[CalendarEvent]:
    seen: set[tuple[str, bool, int]] = set()
    merged: list[CalendarEvent] = []
    for group in groups:
        for event in group:
            key = (event.title.lower(), event.all_day, event.minutes)
            if key in seen:
                continue
            seen.add(key)
            merged.append(event)
    merged.sort(key=lambda event: (0 if event.all_day else 1, event.minutes, event.title.lower()))
    return merged


def format_day(events: list[CalendarEvent], day: date, *, today: date | None = None, limit: int = 12) -> str:
    if today is not None and day == today:
        label = f"Today, {day.strftime('%A, %B')} {day.day}"
    else:
        label = f"{day.strftime('%A, %B')} {day.day}"
    if not events:
        return f"{label}\nNothing scheduled."
    lines = [label]
    for event in events[:limit]:
        if event.all_day or not event.spoken:
            lines.append(f"- {event.title}, all day")
        else:
            lines.append(f"- {event.title} at {event.spoken}")
    extra = len(events) - limit
    if extra > 0:
        lines.append(f"And {extra} more.")
    return "\n".join(lines)


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw:
            continue
        if raw[0] in " \t" and lines:
            lines[-1] = lines[-1] + raw[1:]
        else:
            lines.append(raw)
    return lines


def _property(line: str) -> tuple[str, str, dict[str, str]] | None:
    index = line.find(":")
    if index < 1:
        return None
    left = line[:index]
    value = line[index + 1 :]
    parts = left.split(";")
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, sep, raw = part.partition("=")
        if sep:
            params[key.upper()] = raw
    return parts[0].upper(), value, params


def _ics_text(value: str) -> str:
    text = value.replace("\\n", " ").replace("\\N", " ")
    text = text.replace("\\,", ",").replace("\\;", ";")
    text = text.replace("\\\\", "\\")
    return text.strip()


def _parse_stamp(value: str, params: dict[str, str], zone: ZoneInfo) -> _Stamp | None:
    text = value.strip()
    all_day = params.get("VALUE", "").upper() == "DATE"
    matched = _DATE.fullmatch(text)
    if matched:
        year, month, day = (int(part) for part in matched.groups())
        return _Stamp(datetime(year, month, day, tzinfo=zone), True)
    matched = _UTC.fullmatch(text)
    if matched:
        parts = [int(part) for part in matched.groups()]
        moment = datetime(*parts, tzinfo=timezone.utc).astimezone(zone)
        return _Stamp(moment, False)
    matched = _FLOATING.fullmatch(text)
    if matched:
        parts = [int(part) for part in matched.groups()]
        return _Stamp(datetime(*parts, tzinfo=zone), all_day)
    return None


def _occurs(start: _Stamp, end: _Stamp | None, rule: str, exdates: list[datetime], day: date, zone: ZoneInfo) -> bool:
    if start.at.date() > day:
        return False
    if any(item.date() == day for item in exdates):
        return False
    if not rule:
        if start.all_day and end is not None:
            return start.at.date() <= day < end.at.date()
        return start.at.date() == day
    fields: dict[str, str] = {}
    for part in rule.split(";"):
        key, sep, value = part.partition("=")
        if sep:
            fields[key.upper()] = value
    until = fields.get("UNTIL", "")
    if until:
        parsed = _parse_stamp(until, {}, zone)
        if parsed is not None and parsed.at.date() < day:
            return False
    freq = fields.get("FREQ", "")
    interval = 1
    if "INTERVAL" in fields:
        try:
            interval = int(fields["INTERVAL"])
        except ValueError:
            interval = 1
        if interval < 1:
            interval = 1
    if freq == "DAILY":
        return (day - start.at.date()).days % interval == 0
    if freq == "WEEKLY":
        weeks = (day - start.at.date()).days // 7
        if weeks % interval != 0:
            return False
        if "BYDAY" in fields:
            codes = []
            for code in fields["BYDAY"].split(","):
                clean = _BYDAY_PREFIX.sub("", code.strip(), count=1).upper()
                if clean:
                    codes.append(clean)
        else:
            codes = [_WEEKDAYS[start.at.weekday()]]
        return _WEEKDAYS[day.weekday()] in codes
    if freq == "MONTHLY":
        return start.at.day == day.day
    if freq == "YEARLY":
        return start.at.month == day.month and start.at.day == day.day
    return start.at.date() == day


def _event_on_day(
    props: dict[str, list[tuple[str, dict[str, str]]]],
    day: date,
    zone: ZoneInfo,
) -> CalendarEvent | None:
    status = _first(props, "STATUS")
    if status is not None and status[0].upper() == "CANCELLED":
        return None
    summary = _first(props, "SUMMARY")
    start_prop = _first(props, "DTSTART")
    if summary is None or start_prop is None:
        return None
    start = _parse_stamp(start_prop[0], start_prop[1], zone)
    if start is None:
        return None
    end = None
    end_prop = _first(props, "DTEND")
    if end_prop is not None:
        end = _parse_stamp(end_prop[0], end_prop[1], zone)
    rule = ""
    rule_prop = _first(props, "RRULE")
    if rule_prop is not None:
        rule = rule_prop[0]
    excluded: list[datetime] = []
    for value, params in props.get("EXDATE", []):
        for piece in value.split(","):
            parsed = _parse_stamp(piece.strip(), params, zone)
            if parsed is not None:
                excluded.append(parsed.at)
    if not _occurs(start, end, rule, excluded, day, zone):
        return None
    time_text = "" if start.all_day else f"{start.at.hour:02d}:{start.at.minute:02d}"
    return _make_event(_ics_text(summary[0]), start.all_day, time_text)


def _first(
    props: dict[str, list[tuple[str, dict[str, str]]]],
    name: str,
) -> tuple[str, dict[str, str]] | None:
    values = props.get(name)
    if not values:
        return None
    return values[0]


def _make_event(title: str, all_day: bool, time_text: str) -> CalendarEvent | None:
    name = title.strip().rstrip(".")
    if not name:
        return None
    name = name[:140].strip()
    if all_day or not time_text.strip():
        return CalendarEvent(name, True, "", -1)
    spoken, minutes = _clock(time_text)
    if not spoken:
        return CalendarEvent(name, True, "", -1)
    return CalendarEvent(name, False, spoken, minutes)


def _clock(time_text: str) -> tuple[str, int]:
    matched = _CLOCK.fullmatch(time_text.strip())
    if matched is None:
        return "", -1
    hour = int(matched.group(1))
    minute = int(matched.group(2))
    if minute > 59:
        return "", -1
    marker = matched.group(3)
    if marker:
        if hour < 1 or hour > 12:
            return "", -1
        hour = hour % 12
        if marker.lower() == "pm":
            hour += 12
    elif hour > 23:
        return "", -1
    suffix = "AM" if hour < 12 else "PM"
    shown = hour % 12 or 12
    spoken = f"{shown} {suffix}" if minute == 0 else f"{shown}:{minute:02d} {suffix}"
    return spoken, hour * 60 + minute
