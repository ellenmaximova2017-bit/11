import base64

import anthropic

from . import tools
from .config import ANTHROPIC_API_KEY, MODEL
from .scenarios import DEFAULT_PROMPT

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MAX_STEPS = 8


def attachment_block(data: bytes, kind: str) -> dict:
    """kind: 'image' (jpeg) или 'pdf'."""
    b64 = base64.standard_b64encode(data).decode()
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}


def _system(scenario_prompt, facts):
    s = DEFAULT_PROMPT
    if scenario_prompt:
        s += "\n\nСценарий: " + scenario_prompt
    if facts:
        s += "\n\nЧто ты знаешь о пользователе:\n- " + "\n- ".join(facts)
    s += ("\n\nИспользуй инструменты, когда они помогают выполнить задачу. Новые устойчивые факты о "
          "пользователе сохраняй через remember. Не утверждай, что что-то сделано, если инструмент вернул ошибку.")
    return s


async def ask(history, scenario_prompt=None, attachment=None, ctx: tools.Ctx | None = None,
              model: str = MODEL, facts: list[str] | None = None, use_tools: bool = True) -> str:
    """Агентный цикл: Claude вызывает инструменты, пока не даст финальный ответ."""
    messages = [dict(m) for m in history]
    if attachment and messages and messages[-1]["role"] == "user":
        messages[-1]["content"] = [attachment, {"type": "text", "text": messages[-1]["content"]}]
    tool_list = ([WEB_SEARCH] + tools.specs(ctx)) if (use_tools and ctx) else []
    system = _system(scenario_prompt, facts)
    text = ""
    for _ in range(MAX_STEPS):
        kwargs = {"tools": tool_list} if tool_list else {}
        resp = await client.messages.create(
            model=model, max_tokens=3000, system=system, messages=messages, **kwargs
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip() or text
        if resp.stop_reason == "pause_turn":  # серверный поиск не закончен — продолжаем
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if resp.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": await tools.run(b.name, b.input, ctx)})
        messages.append({"role": "user", "content": results})
    return text or "Не получилось собрать ответ, попробуй переформулировать."
