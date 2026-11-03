from __future__ import annotations

import hashlib
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
        "You are a personal Discord assistant for one person. "
        "Be concise, practical, and friendly. "
        "When they ask you to remember something, save a note. "
        "When they ask to be reminded, create a reminder. "
        "When they want to find a note, search and then read the matching note before you answer. "
        "Delete a note or cancel a reminder only when they clearly ask you to. "
        "Do not invent ids. Use the ids the tools return. "
        f"The current local time is {clock}. "
        f"The timezone is {settings.timezone.key}. "
        f"Tools you can use: {names}."
    )


def run_chat(
    settings: Settings,
    history: list[dict],
    user_text: str,
    tools: list[AssistantTool],
    ctx: ToolContext,
) -> str:
    from xai_sdk import Client
    from xai_sdk.chat import assistant, system, tool, tool_result
    from xai_sdk.chat import user as user_message

    client = Client(api_key=settings.xai_api_key)
    sdk_tools = [
        tool(name=item.name, description=item.description, parameters=item.parameters)
        for item in tools
    ]
    by_name = {item.name: item for item in tools}
    safety_id = hashlib.sha256(f"discord:{ctx.user_id}".encode()).hexdigest()
    chat = client.chat.create(
        model=settings.model,
        tools=sdk_tools or None,
        reasoning_effort=settings.reasoning_effort,
        store_messages=False,
        temperature=0.4,
        max_tokens=2000,
        safety_identifier=safety_id,
    )
    chat.append(system(system_prompt(settings, [item.name for item in tools])))
    for item in history:
        content = str(item.get("content", ""))
        if item.get("role") == "assistant":
            chat.append(assistant(content))
        elif item.get("role") == "user":
            chat.append(user_message(content))
    chat.append(user_message(user_text))

    response = chat.sample()
    last_result = ""
    for _ in range(4):
        calls = list(response.tool_calls or [])
        if not calls:
            break
        chat.append(response)
        for call in calls:
            last_result = invoke_tool(
                by_name,
                ctx,
                call.function.name,
                call.function.arguments,
            )
            log.info("Tool %s finished", call.function.name)
            chat.append(tool_result(last_result, tool_call_id=call.id))
        response = chat.sample()

    text = (response.content or "").strip()
    if text:
        return text
    if last_result:
        return last_result
    return "I couldn't finish that request."
