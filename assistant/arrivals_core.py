"""Arrival messages: the parts that do not need Discord.

Joeii's iPhone runs a Shortcuts automation when he arrives at (or leaves) a
place. It posts a short line like "arrive school" to a Discord webhook in a
private channel. Patricia reads that line and DMs the message he picked for
that place. Only the place name is sent, never GPS coordinates.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Ignore the same ping again this soon. iPhone geofences sometimes fire twice
# when you sit right on the edge of one.
REPEAT_GAP = timedelta(minutes=20)
# A message held for class quiet hours is dropped if it gets this old.
HOLD_LIMIT = timedelta(hours=2)

_KINDS = {
    "arrive": "arrive",
    "arrived": "arrive",
    "arriving": "arrive",
    "at": "arrive",
    "here": "arrive",
    "leave": "leave",
    "left": "leave",
    "leaving": "leave",
}
_PING = re.compile(
    r"^\s*(?:patricia[\s,:]+)?(?P<kind>[a-z]+)\b(?:\s+(?:at|from|to))?[\s:\-]*(?P<place>.+?)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def place_key(name: str) -> str:
    """'  My  House ' and 'my house' are the same place."""
    return " ".join(re.sub(r"[^\w\s'-]", " ", name.lower()).split())


def place_label(name: str) -> str:
    return " ".join(name.split())[:60]


def parse_ping(text: str) -> tuple[str, str] | None:
    """'arrive school' -> ('arrive', 'school'). None if it isn't a ping."""
    match = _PING.match(text or "")
    if not match:
        return None
    kind = _KINDS.get(match["kind"].lower())
    place = place_label(match["place"])
    if kind is None or not place_key(place):
        return None
    return kind, place


def is_repeat(last_iso: str | None, now: datetime) -> bool:
    if not last_iso:
        return False
    return now - datetime.fromisoformat(last_iso) < REPEAT_GAP


def ping_text(kind: str, place: str) -> str:
    """What the iPhone Shortcut should send."""
    return f"{kind} {place_key(place)}"


def describe(place: dict) -> str:
    parts = [f"**{place['label']}**"]
    if place.get("arrive_text"):
        parts.append(f"  arrive: {place['arrive_text']}")
    if place.get("leave_text"):
        parts.append(f"  leave: {place['leave_text']}")
    return "\n".join(parts)
