from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

from assistant.config import Settings
from assistant.tools import AssistantTool, ToolContext, invoke_tool

log = logging.getLogger(__name__)


def system_prompt(settings: Settings, tool_names: list[str]) -> str:
    now = datetime.now(settings.timezone)
    names = ", ".join(tool_names) if tool_names else "none"
    clock = now.strftime("%A, %B %d, %Y %I:%M %p %Z")
    return (
        "You are Patricia, Joeii's private assistant on this PC. "
        "Be calm, brief, and practical. "
        "Speak to Joeii directly. "
        "Use tools for the calendar, the weather, reminders, and notes. "
        "Do not guess what is on the calendar or what the weather is. "
        "The calendar is read-only. You cannot add, change, or delete events. "
        "When Joeii asks you to remember something, save a note. "
        "When Joeii asks to be reminded, create a reminder. "
        "When Joeii wants to find a note, search and then read the matching note before you answer. "
        "Delete a note or cancel a reminder only when clearly asked. "
        "Do not invent ids. Use the ids the tools return. "
        f"The current local time is {clock}. "
        f"The timezone is {settings.timezone.key}. "
        f"Tools you can use: {names}."
    )


def _clean_history(history: list[dict]) -> list[dict]:
    """Claude needs alternating user/assistant turns that start with the user."""
    cleaned: list[dict] = []
    for item in history:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in ("user", "assistant") or not content:
            continue
        if not cleaned and role == "assistant":
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n\n" + content
        else:
            cleaned.append({"role": role, "content": content})
    if cleaned and cleaned[-1]["role"] == "user":
        cleaned.pop()
    return cleaned


def run_chat(
    settings: Settings,
    history: list[dict],
    user_text: str,
    tools: list[AssistantTool],
    ctx: ToolContext,
) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    api_tools = [
        {
            "name": item.name,
            "description": item.description,
            "input_schema": item.parameters or {"type": "object", "properties": {}},
        }
        for item in tools
    ]
    by_name = {item.name: item for item in tools}
    safety_id = hashlib.sha256(f"discord:{ctx.user_id}".encode()).hexdigest()
    messages = _clean_history(history)
    messages.append({"role": "user", "content": user_text})
    request = {
        "model": settings.model,
        "max_tokens": 2000,
        "temperature": 0.4,
        "system": system_prompt(settings, [item.name for item in tools]),
        "metadata": {"user_id": safety_id},
    }
    if api_tools:
        request["tools"] = api_tools

    response = client.messages.create(messages=messages, **request)
    last_result = ""
    for _ in range(4):
        calls = [block for block in response.content if block.type == "tool_use"]
        if not calls:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in calls:
            last_result = invoke_tool(by_name, ctx, call.name, json.dumps(call.input or {}))
            log.info("Tool %s finished", call.name)
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": last_result}
            )
        messages.append({"role": "user", "content": results})
        response = client.messages.create(messages=messages, **request)

    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    if text:
        return text
    if last_result:
        return last_result
    return "I couldn't finish that request."
