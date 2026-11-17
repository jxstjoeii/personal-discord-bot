"""Small fun things: dice, coins, a magic 8-ball, and an Overwatch hero picker."""

from __future__ import annotations

import random
import re

import discord
from discord import app_commands

from assistant.addons.base import Addon
from assistant.morning_core import random_hero
from assistant.tools import AssistantTool

EIGHT_BALL = [
    "It is certain. ✨", "Without a doubt.", "You may rely on it.", "Yes, definitely.",
    "Most likely.", "Outlook good.", "Signs point to yes.", "Ask again after a snack.",
    "Better not tell you now. 👀", "Cannot predict now. Try again.", "Concentrate and ask again.",
    "Don't count on it.", "My sources say no.", "Outlook not so good.", "Very doubtful.",
]


def roll(spec: str = "1d6", rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    match = re.fullmatch(r"\s*(\d*)\s*d\s*(\d+)\s*([+-]\s*\d+)?\s*", spec.lower() or "1d6")
    if not match:
        return "Try something like 1d20, 2d6, or 3d8+2."
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    bonus = int((match.group(3) or "0").replace(" ", ""))
    if not (1 <= count <= 50 and 2 <= sides <= 1000):
        return "Keep it to 1 to 50 dice with 2 to 1000 sides."
    rolls = [rng.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + bonus
    shown = ", ".join(map(str, rolls))
    extra = f" {'+' if bonus >= 0 else '-'} {abs(bonus)}" if bonus else ""
    if count == 1 and not bonus:
        return f"🎲 You rolled a **{total}** (d{sides})."
    return f"🎲 {count}d{sides}{extra}: [{shown}]{extra} = **{total}**"


def flip(rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    return "🪙 **Heads!**" if rng.random() < 0.5 else "🪙 **Tails!**"


def eight_ball(rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    return f"🎱 {rng.choice(EIGHT_BALL)}"


def hero_pick(role: str = "", rng: random.Random | None = None) -> str:
    hero, picked = random_hero(role or None, rng)
    return f"🎮 Play **{hero}** ({picked}). No take-backs!"


class Fun(Addon):
    addon_name = "fun"
    addon_description = "Dice, coin flips, a magic 8-ball, and a random Overwatch hero picker."

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="roll_dice",
                description="Roll dice, like 1d20 or 2d6+3. Use when Joeii asks to roll.",
                parameters={"type": "object", "properties": {"dice": {"type": "string"}}, "required": []},
                handler=lambda ctx, dice="1d6": roll(dice),
            ),
            AssistantTool(
                name="flip_coin",
                description="Flip a coin. Use when Joeii asks for a coin flip or can't decide between two things.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: flip(),
            ),
            AssistantTool(
                name="magic_8_ball",
                description="Shake the magic 8-ball for a yes or no question.",
                parameters={"type": "object", "properties": {}},
                handler=lambda ctx: eight_ball(),
            ),
            AssistantTool(
                name="pick_overwatch_hero",
                description="Pick a random Overwatch hero, optionally for a role (Tank, Damage, Support).",
                parameters={"type": "object", "properties": {"role": {"type": "string"}}},
                handler=lambda ctx, role="": hero_pick(role),
            ),
        ]

    @app_commands.command(name="roll", description="Roll dice, like 1d20 or 2d6")
    @app_commands.describe(dice="Like 1d20, 2d6, or 3d8+2")
    async def roll_command(self, interaction: discord.Interaction, dice: str = "1d6") -> None:
        await interaction.response.send_message(roll(dice))

    @app_commands.command(name="flip", description="Flip a coin")
    async def flip_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(flip())

    @app_commands.command(name="8ball", description="Ask the magic 8-ball a yes or no question")
    @app_commands.describe(question="Your yes or no question")
    async def eight_ball_command(self, interaction: discord.Interaction, question: str) -> None:
        await interaction.response.send_message(f"> {question}\n{eight_ball()}")

    @app_commands.command(name="hero", description="Pick a random Overwatch hero for you")
    @app_commands.choices(role=[
        app_commands.Choice(name="Any", value=""),
        app_commands.Choice(name="Tank", value="Tank"),
        app_commands.Choice(name="Damage", value="Damage"),
        app_commands.Choice(name="Support", value="Support"),
    ])
    async def hero_command(self, interaction: discord.Interaction, role: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.send_message(hero_pick(role.value if role else ""))


async def setup(bot) -> None:
    await bot.add_cog(Fun(bot))
