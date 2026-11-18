from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from assistant.config import Settings
from assistant.db import Database

log = logging.getLogger(__name__)


@dataclass
class ToolContext:
    user_id: int
    settings: Settings
    db: Database
    channel_id: int | None = None


@dataclass
class ToolResult:
    """A tool answer that also carries pictures, such as screenshots."""

    text: str
    images: list = field(default_factory=list)  # assistant.vision.Picture items

    def __str__(self) -> str:
        return self.text


@dataclass
class AssistantTool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]


def collect_tools(bot) -> list[AssistantTool]:
    ordered: list[AssistantTool] = []
    index: dict[str, int] = {}
    for cog in bot.cogs.values():
        method = getattr(cog, "assistant_tools", None)
        if not callable(method):
            continue
        for item in method():
            if item.name in index:
                log.warning(
                    "Tool %s from %s replaces an earlier tool",
                    item.name,
                    cog.__class__.__name__,
                )
                ordered[index[item.name]] = item
            else:
                index[item.name] = len(ordered)
                ordered.append(item)
    return ordered


def invoke_tool(
    tools: dict[str, AssistantTool],
    ctx: ToolContext,
    name: str,
    raw_arguments: str | None,
) -> str:
    chosen = tools.get(name)
    if chosen is None:
        return json.dumps({"error": f"Unknown tool {name}"})
    try:
        parsed = json.loads((raw_arguments or "").strip() or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "Bad tool arguments"})
    if not isinstance(parsed, dict):
        return json.dumps({"error": "Tool arguments must be an object"})
    try:
        signature = inspect.signature(chosen.handler)
        accepted = {
            key: value
            for key, value in parsed.items()
            if key in signature.parameters and key != "ctx"
        }
        result = chosen.handler(ctx, **accepted)
    except Exception as exc:
        log.exception("Tool %s failed", name)
        return json.dumps({"error": str(exc)})
    if isinstance(result, ToolResult):
        result.text = result.text[:4000]
        return result
    return str(result)[:4000]
