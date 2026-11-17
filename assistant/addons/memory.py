from __future__ import annotations

import discord
from discord import app_commands

from assistant import memory
from assistant.addons.base import Addon
from assistant.formatting import split_discord
from assistant.tools import AssistantTool, ToolContext


class Memory(Addon):
    addon_name = "memory"
    addon_description = "A private file of things Patricia has learned about you."

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="remember_about_joeii",
                description=(
                    "Save a lasting fact or preference about Joeii to his private about-me file, "
                    "like his main heroes, his classes, his motorcycle, foods he likes, or how he "
                    "wants to be reminded. Write it as one short sentence about him. Do not save "
                    "passing moods, one-off plans (use reminders), or things he asks you not to keep."
                ),
                parameters={
                    "type": "object",
                    "properties": {"fact": {"type": "string", "description": "One short sentence, like: Mains Mercy and Kiriko."}},
                    "required": ["fact"],
                },
                handler=lambda ctx, fact: memory.remember(fact),
            ),
            AssistantTool(
                name="forget_about_joeii",
                description="Remove saved facts about Joeii that contain these words. Use when he asks you to forget something.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "Words from the fact to remove."}},
                    "required": ["text"],
                },
                handler=lambda ctx, text: memory.forget(text),
            ),
        ]

    @app_commands.command(name="aboutme", description="See what Patricia remembers about you")
    async def aboutme(self, interaction: discord.Interaction) -> None:
        items = memory.facts()
        if not items:
            await interaction.response.send_message(
                "I haven't saved anything about you yet. Tell me things like your main heroes or your classes, "
                "and I'll remember them."
            )
            return
        text = "**What I know about you** (only on your PC, never on GitHub):\n" + "\n".join(f"• {item}" for item in items)
        parts = split_discord(text)
        await interaction.response.send_message(parts[0])
        for part in parts[1:]:
            await interaction.followup.send(part)


async def setup(bot) -> None:
    await bot.add_cog(Memory(bot))
