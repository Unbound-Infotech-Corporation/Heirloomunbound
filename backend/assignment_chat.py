"""Draft an assignment with the same LlmChat path Twin turns use.

No tools. The model may only propose an outbound action. This module is
imported when a step runs, not by the pure unit tests.
"""
from __future__ import annotations

ASSIGNMENT_SYSTEM = (
    "You draft work inside Heirloom for the owner. "
    "You never send email, post, delete, or spend. "
    "If the job would do one of those, propose it in ACTION and PAYLOAD. "
    "Do not claim you already did it."
)


async def complete_assignment_prompt(prompt: str) -> str:
    from deps import EMERGENT_LLM_KEY

    if not (EMERGENT_LLM_KEY or "").strip():
        raise RuntimeError("no model key")
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id="heirloom-assignment",
            system_message=ASSIGNMENT_SYSTEM,
        )
        .with_model("anthropic", "claude-sonnet-4-6")
    )
    result = await chat.send_message(UserMessage(text=prompt))
    if isinstance(result, str):
        text = result.strip()
    else:
        content = getattr(result, "content", None)
        text = content.strip() if isinstance(content, str) else str(result or "").strip()
    if not text:
        raise RuntimeError("model returned empty content")
    return text
