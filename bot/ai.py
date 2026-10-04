import base64

import anthropic

from .config import ANTHROPIC_API_KEY, MODEL
from .scenarios import DEFAULT_PROMPT

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


def attachment_block(data: bytes, kind: str) -> dict:
    """kind: 'image' (jpeg) или 'pdf'."""
    b64 = base64.standard_b64encode(data).decode()
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}


async def ask(history: list[dict], scenario_prompt: str | None = None, attachment: dict | None = None) -> str:
    """history — текстовая история; attachment вкладывается в последнее сообщение пользователя."""
    system = DEFAULT_PROMPT + ("\n\nСценарий: " + scenario_prompt if scenario_prompt else "")
    messages = [dict(m) for m in history]
    if attachment and messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = [attachment, {"type": "text", "text": messages[-1]["content"]}]
    resp = await client.messages.create(
        model=MODEL, max_tokens=2000, system=system, messages=messages, tools=TOOLS
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or "Не получилось собрать ответ, попробуй переформулировать."
