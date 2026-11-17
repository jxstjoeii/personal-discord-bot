"""What Patricia knows about Joeii: a small file that only lives on this PC.

The file is data/about-joeii.md. The data folder is in .gitignore, so the
hourly sync never pushes it to GitHub. It is sent to Claude with each chat so
Patricia can use it.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from assistant.config import ROOT

PATH = ROOT / "data" / "about-joeii.md"
MAX_FACTS = 150
MAX_FACT_LENGTH = 300
HEADER = (
    "# About Joeii\n\n"
    "Things Patricia has learned. This file stays on this PC and is never pushed to GitHub.\n"
    "You can edit it by hand: one fact per line, starting with \"- \".\n\n"
)
_lock = threading.Lock()


def _path(path: Path | None) -> Path:
    return path or PATH


def facts(path: Path | None = None) -> list[str]:
    file = _path(path)
    if not file.exists():
        return []
    lines = file.read_text(encoding="utf-8").splitlines()
    return [line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip()]


def _write(items: list[str], path: Path | None) -> None:
    file = _path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"- {item}\n" for item in items)
    temp = file.with_suffix(".tmp")
    temp.write_text(HEADER + body, encoding="utf-8")
    temp.replace(file)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def remember(fact: str, path: Path | None = None, today: datetime | None = None) -> str:
    fact = " ".join(fact.split())[:MAX_FACT_LENGTH]
    if not fact:
        return "There was nothing to remember."
    with _lock:
        items = facts(path)
        if any(_norm(fact) == _norm(item.split(" (since ")[0]) for item in items):
            return "I already knew that."
        stamp = (today or datetime.now()).strftime("%b %Y")
        items.append(f"{fact} (since {stamp})")
        if len(items) > MAX_FACTS:
            items = items[-MAX_FACTS:]
        _write(items, path)
    return f"Saved to what I know about Joeii: {fact}"


def forget(text: str, path: Path | None = None) -> str:
    wanted = _norm(text)
    if not wanted:
        return "Tell me what to forget."
    with _lock:
        items = facts(path)
        kept = [item for item in items if wanted not in _norm(item)]
        removed = len(items) - len(kept)
        if removed:
            _write(kept, path)
    if not removed:
        return "I didn't have anything saved like that."
    return f"Forgot {removed} thing(s) about Joeii."


def prompt_block(path: Path | None = None, limit: int = 5000) -> str:
    items = facts(path)
    if not items:
        return "Nothing saved about Joeii yet."
    text = "\n".join(f"- {item}" for item in items)
    return text[-limit:]
