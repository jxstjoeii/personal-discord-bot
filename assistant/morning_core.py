"""The morning hello: the parts that do not need Discord."""

from __future__ import annotations

import logging
import random
from datetime import date, datetime

log = logging.getLogger(__name__)

# Edit freely. New heroes can be added at the end of their role.
HEROES = {
    "Tank": [
        "D.Va", "Doomfist", "Hazard", "Junker Queen", "Mauga", "Orisa", "Ramattra",
        "Reinhardt", "Roadhog", "Sigma", "Winston", "Wrecking Ball", "Zarya",
    ],
    "Damage": [
        "Ashe", "Bastion", "Cassidy", "Echo", "Freja", "Genji", "Hanzo", "Junkrat", "Mei",
        "Pharah", "Reaper", "Sojourn", "Soldier: 76", "Sombra", "Symmetra", "Torbjörn",
        "Tracer", "Venture", "Widowmaker",
    ],
    "Support": [
        "Ana", "Baptiste", "Brigitte", "Illari", "Juno", "Kiriko", "Lifeweaver", "Lúcio",
        "Mercy", "Moira", "Wuyang", "Zenyatta",
    ],
}


def hero_of_the_day(day: date) -> tuple[str, str]:
    """Same hero all day, a different one tomorrow."""
    rng = random.Random(day.toordinal() * 7919)
    role = rng.choice(list(HEROES))
    return rng.choice(HEROES[role]), role


def random_hero(role: str | None = None, rng: random.Random | None = None) -> tuple[str, str]:
    rng = rng or random.Random()
    roles = [r for r in HEROES if role is None or r.lower() == role.lower()] or list(HEROES)
    picked = rng.choice(roles)
    return rng.choice(HEROES[picked]), picked


def riding_rules(briefing_config: dict | None) -> str:
    rules = {}
    if isinstance(briefing_config, dict) and isinstance(briefing_config.get("motorcycle"), dict):
        rules = briefing_config["motorcycle"]
    return (
        f"Riding window {rules.get('ridingStart', '08:00')} to {rules.get('ridingEnd', '19:00')}. "
        f"Good riding needs at least {rules.get('minTemp', 50)} and at most {rules.get('maxTemp', 95)} "
        f"degrees, rain chance at most {rules.get('maxPrecipProbability', 30)}%, and calm wind "
        f"(under {rules.get('maxWind', 25)} mph, gusts under {rules.get('maxGust', 35)})."
    )


def fallback(name: str, facts: dict) -> str:
    """Plain version when Claude can't be reached."""
    lines = [f"☀️ **Good morning, {name}!**", ""]
    lines.append(facts["weather"])
    if facts["due"]:
        lines += ["", "📚 **Due soon**", facts["due"]]
    if facts["reminders"]:
        lines += ["", "⏰ **Today's reminders**", facts["reminders"]]
    lines += ["", f"🎮 Hero of the day: **{facts['hero']}** ({facts['role']})."]
    return "\n".join(lines)


def write_hello(settings, facts: dict, about: str, now: datetime) -> str:
    try:
        from assistant.brain import agent

        system = (
            "You are Patricia, Joeii's warm, slightly playful assistant. Write his morning hello "
            "for Discord. Keep it under 900 characters and easy to skim, using a few emoji and "
            "short bold labels. Include, in this order: a one-line greeting for the day; the "
            "weather in one or two lines; a clear motorcycle verdict (yes, later today, or no, "
            "with the reason) using the riding rules; what's due soon and today's reminders, only "
            "if there are any; and one fun closer: the hero of the day with a tiny, doable "
            "challenge, plus either a short clean joke or an Overwatch fun fact you are sure is "
            "true. Use what you know about him lightly. Do not invent calendar events, reminders, "
            "or weather. Reply with only the message."
        )
        prompt = (
            f"Today is {now.strftime('%A, %B %d')}.\n\n"
            f"Weather:\n{facts['weather']}\n\n"
            f"Riding rules: {facts['riding']}\n\n"
            f"Calendar:\n{facts['calendar']}\n\n"
            f"Due soon:\n{facts['due'] or 'Nothing due in the next 3 days.'}\n\n"
            f"Reminders today:\n{facts['reminders'] or 'None.'}\n\n"
            f"Hero of the day: {facts['hero']} ({facts['role']})\n\n"
            f"What you know about Joeii:\n{about}"
        )
        text = agent(settings, system, prompt, [], lambda name, args: "", max_turns=1).strip()
        if text and len(text) <= 1900:
            return text
    except Exception as exc:
        log.warning("Writing the morning hello failed, so a plain one is used: %s", exc)
    return fallback("Joeii", facts)
