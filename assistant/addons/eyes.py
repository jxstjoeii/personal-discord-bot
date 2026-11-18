from __future__ import annotations

from assistant import vision
from assistant.addons.base import Addon
from assistant.tools import AssistantTool, ToolContext, ToolResult


class Eyes(Addon):
    addon_name = "eyes"
    addon_description = "Lets Patricia see pictures you send, and glance at your screen when you ask."

    def assistant_tools(self) -> list[AssistantTool]:
        return [
            AssistantTool(
                name="look_at_screen",
                description=(
                    "Take a screenshot of Joeii's PC screens and look at it. Use ONLY when he asks you "
                    "to look at, check, or read his screen right now. Never use it on your own or in "
                    "scheduled jobs. While a game is running the game screen is left out unless he "
                    "asks for it."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "which": {
                            "type": "string",
                            "enum": ["all", "discord", "main"],
                            "description": "all screens, the one with Discord, or the main screen. Default all.",
                        },
                        "include_game_screen": {
                            "type": "boolean",
                            "description": "True only if he explicitly asks to see his game.",
                        },
                    },
                },
                handler=self._look,
            )
        ]

    def _look(self, ctx: ToolContext, which: str = "all", include_game_screen: bool = False) -> ToolResult:
        pictures, note = vision.capture(ctx.settings, which, bool(include_game_screen))
        return ToolResult(note, pictures)


async def setup(bot) -> None:
    await bot.add_cog(Eyes(bot))
