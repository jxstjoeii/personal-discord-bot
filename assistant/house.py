from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from assistant.ics import events_from_ics, events_from_local, format_day, merge_events

log = logging.getLogger(__name__)

DEFAULT_BRIEFING = Path(r"C:\Users\joeii\OneDrive\Documents\morning-briefing")


class FeedError(Exception):
    def __init__(self, host: str, code: int | None) -> None:
        self.host = host
        self.code = code
        super().__init__("calendar feed failed")
_DIRECT = {
    "brief": "brief",
    "status": "brief",
    "calendar": "calendar",
    "weather": "weather",
}


def direct_kind(text: str) -> str | None:
    return _DIRECT.get(text.strip().lower().rstrip("."))


def chosen_days(now: datetime, day: str) -> list[date]:
    today = now.date()
    key = (day or "both").strip().lower()
    if key == "today":
        return [today]
    if key == "tomorrow":
        return [today + timedelta(days=1)]
    return [today, today + timedelta(days=1)]


def calendar_report(
    zone: ZoneInfo,
    now: datetime,
    day: str = "both",
    *,
    briefing: Path | None = None,
    fetch_text=None,
) -> str:
    try:
        root, config = load_briefing(briefing)
    except (OSError, json.JSONDecodeError, ValueError):
        return "I can't read the morning briefing calendar on this PC."
    fetch = fetch_text or _fetch_text
    local_data, feeds, failures, connected = _load_calendar(root, config, fetch)
    if not connected:
        return "No calendar is connected. The morning briefing has no calendar feeds."
    blocks = []
    for item in chosen_days(now, day):
        groups = []
        if local_data is not None:
            groups.append(events_from_local(local_data, item))
        for text in feeds:
            groups.append(events_from_ics(text, item, zone))
        blocks.append(format_day(merge_events(groups), item, today=now.date()))
    note = _feed_note(failures)
    if note:
        blocks.append(note)
    return "\n\n".join(blocks)


def weather_report(
    zone: ZoneInfo,
    now: datetime,
    day: str = "both",
    *,
    briefing: Path | None = None,
    fetch_text=None,
    location: str | None = None,
) -> str:
    fetch = fetch_text or _fetch_text
    place = None
    try:
        _root, config = load_briefing(briefing)
        place = _location(config)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    wanted = (os.getenv("WEATHER_LOCATION", "") if location is None else location).strip()
    if wanted:
        units = place[3] if place else _units(os.getenv("WEATHER_UNITS", "fahrenheit"))
        try:
            place = _resolve_place(wanted, units, fetch)
        except Exception as exc:
            log.warning("Could not find WEATHER_LOCATION %r: %s", wanted, exc)
            return (
                f"I couldn't find the place \"{wanted}\" from WEATHER_LOCATION. Try a city and "
                "state or country, like Portland, OR, or numbers like 45.52, -122.68."
            )
    if place is None:
        return (
            "I don't know where home is. Put WEATHER_LOCATION=Your City, State in the .env file, "
            "then restart Patricia."
        )
    name, lat, lon, units, tz_name = place
    try:
        payload = json.loads(fetch(_weather_url(lat, lon, tz_name, units)))
    except FeedError as exc:
        log.warning("Weather lookup failed: %s %s", exc.host, exc.code)
        code = f" (error {exc.code})" if exc.code else ""
        return f"The weather service didn't answer just now{code}. Try again in a few minutes."
    except Exception as exc:
        log.warning("Weather lookup failed: %s", exc)
        return "The weather service sent something I couldn't read. Try again in a few minutes."
    if not isinstance(payload, dict) or "daily" not in payload:
        log.warning("Weather lookup returned no forecast: %s", str(payload)[:200])
        return "The weather service didn't send a forecast. Try again in a few minutes."
    return _format_weather(payload, name, units, now, chosen_days(now, day), zone)


_STATES = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas", "ca": "california",
    "co": "colorado", "ct": "connecticut", "de": "delaware", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana", "ia": "iowa",
    "ks": "kansas", "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland",
    "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi",
    "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada", "nh": "new hampshire",
    "nj": "new jersey", "nm": "new mexico", "ny": "new york", "nc": "north carolina",
    "nd": "north dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon", "pa": "pennsylvania",
    "ri": "rhode island", "sc": "south carolina", "sd": "south dakota", "tn": "tennessee",
    "tx": "texas", "ut": "utah", "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia",
}
_PLACES: dict[tuple[str, str], tuple[str, float, float, str, str]] = {}


def _units(text: str) -> str:
    return "celsius" if str(text).strip().lower() in {"c", "celsius", "metric"} else "fahrenheit"


def _resolve_place(text: str, units: str, fetch) -> tuple[str, float, float, str, str]:
    """A city name or 'lat, lon' -> (name, lat, lon, units, timezone)."""
    key = (text.lower(), units)
    if key in _PLACES:
        return _PLACES[key]
    numbers = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text)
    if numbers:
        lat, lon = float(numbers.group(1)), float(numbers.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("coordinates out of range")
        place = ("", lat, lon, units, "auto")
    else:
        name, _, extra = text.partition(",")
        data = json.loads(
            fetch(
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={quote(name.strip())}&count=10&language=en&format=json"
            )
        )
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            raise ValueError("no matching place")
        pick = results[0]
        extra = extra.strip().lower()
        if extra:
            wanted = {extra, _STATES.get(extra, extra)}
            for item in results:
                fields = {str(item.get(k) or "").lower() for k in ("admin1", "admin2", "country", "country_code")}
                if wanted & fields or any(f.startswith(extra) for f in fields if f):
                    pick = item
                    break
        label = ", ".join(str(x) for x in (pick.get("name"), pick.get("admin1")) if x)
        place = (label, float(pick["latitude"]), float(pick["longitude"]), units, str(pick.get("timezone") or "auto"))
    _PLACES[key] = place
    return place


def brief_report(
    zone: ZoneInfo,
    now: datetime,
    reminder_lines: list[str] | None = None,
    *,
    briefing: Path | None = None,
    fetch_text=None,
) -> str:
    clock = _clock(now)
    weather = weather_report(zone, now, "both", briefing=briefing, fetch_text=fetch_text)
    calendar = calendar_report(zone, now, "both", briefing=briefing, fetch_text=fetch_text)
    if reminder_lines:
        reminders = "\n".join(reminder_lines)
    else:
        reminders = "No upcoming reminders."
    return f"{clock}\n\n{weather}\n\n{calendar}\n\nReminders\n{reminders}"


def load_briefing(path: Path | None = None) -> tuple[Path, dict]:
    root = DEFAULT_BRIEFING if path is None else path
    config_path = root / "config.json" if root.is_dir() else root
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("config")
    return config_path.parent, data


def _load_calendar(root: Path, config: dict, fetch_text) -> tuple[object, list[str], int, bool]:
    calendar = config.get("calendar")
    if not isinstance(calendar, dict):
        calendar = {}
    local_data = None
    failures: list[FeedError] = []
    connected = False
    if calendar.get("useLocal", True) is not False:
        rel = str(calendar.get("localFile") or "calendar/events.json")
        local_path = Path(rel)
        if not local_path.is_absolute():
            local_path = root / local_path
        if local_path.is_file():
            connected = True
            try:
                local_data = json.loads(local_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                failures.append(FeedError("local calendar", None))
    urls = calendar.get("icsUrls") or []
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, list):
        urls = []
    feeds: list[str] = []
    for raw in urls:
        link = _https_calendar_url(str(raw))
        if not link:
            continue
        connected = True
        try:
            feeds.append(fetch_text(link))
        except FeedError as exc:
            log.warning("Calendar feed failed: %s %s", exc.host, exc.code)
            failures.append(exc)
        except Exception:
            log.warning("Calendar feed failed")
            failures.append(FeedError("calendar", None))
    return local_data, feeds, failures, connected


def _feed_note(failures: list[FeedError]) -> str:
    notes = []
    for exc in failures:
        if exc.code == 404 and "icloud" in exc.host:
            notes.append("The iCloud calendar link returned Not Found.")
        else:
            notes.append("One calendar feed did not answer.")
    return " ".join(notes)


def _https_calendar_url(link: str) -> str:
    text = link.strip()
    if text.startswith("webcal://"):
        return "https://" + text[9:]
    if text.startswith("webcals://"):
        return "https://" + text[10:]
    return text


def _location(config: dict) -> tuple[str, float, float, str, str] | None:
    place = config.get("location")
    if not isinstance(place, dict):
        return None
    try:
        lat = float(place.get("latitude"))
        lon = float(place.get("longitude"))
    except (TypeError, ValueError):
        return None
    units = _units(place.get("units") or "fahrenheit")
    name = str(place.get("name") or "").strip()
    tz_name = str(place.get("timezone") or "auto").strip() or "auto"
    return name, lat, lon, units, tz_name


def _weather_url(lat: float, lon: float, tz_name: str, units: str) -> str:
    temp = "celsius" if units == "celsius" else "fahrenheit"
    wind = "kmh" if temp == "celsius" else "mph"
    precip = "mm" if temp == "celsius" else "inch"
    tz_param = "auto" if tz_name == "auto" else quote(tz_name)
    lat_text = format(lat, ".6f").rstrip("0").rstrip(".")
    lon_text = format(lon, ".6f").rstrip("0").rstrip(".")
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat_text}&longitude={lon_text}&timezone={tz_param}"
        f"&temperature_unit={temp}&wind_speed_unit={wind}&precipitation_unit={precip}"
        "&forecast_days=2"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&hourly=temperature_2m,weather_code,precipitation_probability"
    )


def _format_weather(
    payload: dict,
    place: str,
    units: str,
    now: datetime,
    days: list[date],
    zone: ZoneInfo,
) -> str:
    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    times = daily.get("time") if isinstance(daily.get("time"), list) else []
    unit = "C" if units == "celsius" else "F"
    lines: list[str] = []
    for index, item in enumerate(days):
        key = item.isoformat()
        label = "Today" if item == now.date() else item.strftime("%A")
        if key not in times:
            lines.append(f"{label}: no forecast.")
            continue
        slot = times.index(key)
        code = int(round(_series(daily.get("weather_code"), slot)))
        high = int(round(_series(daily.get("temperature_2m_max"), slot)))
        low = int(round(_series(daily.get("temperature_2m_min"), slot)))
        chance = int(round(_series(daily.get("precipitation_probability_max"), slot)))
        where = f" in {place}" if place and index == 0 else ""
        if item == now.date():
            current = _current(payload, now, zone)
            if current is not None:
                temp, now_code = current
                lines.append(f"Right now{where}: {temp} {unit} and {_weather_word(now_code)}.")
                where = ""
            soon = _next_hours(payload, now, zone, unit)
            if soon:
                lines.append(f"Next few hours: {soon}.")
        lines.append(
            f"{label}{where}: {_weather_word(code)}, high {high} {unit}, low {low} {unit}. "
            f"Rain chance {chance}%."
        )
    return "\n".join(lines) if lines else "I couldn't check the weather."


def _current(payload: dict, now: datetime, zone: ZoneInfo) -> tuple[int, int] | None:
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    best = None
    best_at = None
    limit = now + timedelta(minutes=40)
    for index, stamp in enumerate(times):
        moment = _local_stamp(str(stamp), zone)
        if moment is None or moment > limit:
            continue
        best = index
        best_at = moment
    if best is None or best_at is None:
        return None
    if abs((now - best_at).total_seconds()) > 90 * 60:
        return None
    temp = int(round(_series(hourly.get("temperature_2m"), best)))
    code = int(round(_series(hourly.get("weather_code"), best)))
    return temp, code


def _next_hours(payload: dict, now: datetime, zone: ZoneInfo, unit: str) -> str:
    """Every other hour for the next six hours."""
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    picked = []
    for index, stamp in enumerate(times):
        moment = _local_stamp(str(stamp), zone)
        if moment is None or moment <= now or moment > now + timedelta(hours=6):
            continue
        picked.append((index, moment))
    parts = []
    for index, moment in picked[1::2][:3] or picked[:3]:
        hour = moment.strftime("%I").lstrip("0") or "12"
        temp = int(round(_series(hourly.get("temperature_2m"), index)))
        word = _weather_word(int(round(_series(hourly.get("weather_code"), index))))
        rain = int(round(_series(hourly.get("precipitation_probability"), index)))
        text = f"{hour} {moment.strftime('%p')} {temp} {unit} {word}"
        if rain >= 10:
            text += f" ({rain}% rain)"
        parts.append(text)
    return ", ".join(parts)


def _local_stamp(value: str, zone: ZoneInfo) -> datetime | None:
    text = value.strip().replace("Z", "")
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=zone)
    return moment.astimezone(zone)


def _series(values: object, index: int) -> float:
    if not isinstance(values, list) or index < 0 or index >= len(values) or values[index] is None:
        return 0.0
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return 0.0


def _weather_word(code: int) -> str:
    if code == 0:
        return "clear"
    if code == 1:
        return "mostly clear"
    if code == 2:
        return "partly cloudy"
    if code == 3:
        return "overcast"
    if code in {45, 48}:
        return "foggy"
    if 51 <= code <= 57:
        return "drizzly"
    if 61 <= code <= 67:
        return "rainy"
    if 71 <= code <= 77 or code in {85, 86}:
        return "snowy"
    if 80 <= code <= 82:
        return "showery"
    if 95 <= code <= 99:
        return "stormy"
    return "changeable"


def _clock(now: datetime) -> str:
    hour = now.strftime("%I").lstrip("0") or "12"
    return f"{now.strftime('%A, %B')} {now.day}, {now.year}, {hour}:{now.strftime('%M %p')}"


def _fetch_text(url: str) -> str:
    host = urlparse(url).hostname or "calendar"
    request = urllib.request.Request(url, headers={"User-Agent": "Patricia/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read(2_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise FeedError(host, exc.code) from None
    except Exception:
        raise FeedError(host, None) from None
