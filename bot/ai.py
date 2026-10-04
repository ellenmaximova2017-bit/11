import anthropic

from .config import ANTHROPIC_API_KEY, MODEL
from .scenarios import DEFAULT_PROMPT

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]


async def ask(history: list[dict], scenario_prompt: str | None = None) -> str:
    system = DEFAULT_PROMPT + ("\n\nСценарий: " + scenario_prompt if scenario_prompt else "")
    resp = await client.messages.create(
        model=MODEL, max_tokens=2000, system=system, messages=history, tools=TOOLS
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text or "Не получилось собрать ответ, попробуй переформулировать."
