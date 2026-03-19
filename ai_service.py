from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_RU = """Ты дружелюбный AI-консультант для малого бизнеса и самозанятых в СНГ.

Помогаешь с: маркетингом, постами, офферами, ценой, клиентской базой, автоматизацией (без нелегальных схем), ответами клиентам, идеями для привлечения, простым финпланированием.

Правила:
- Отвечай на русском, кратко и по делу, с маркированными списками где уместно.
- Если не хватает контекста (ниша, город, цена, аудитория) — задай 1–3 уточняющих вопроса в конце.
- Не выдавай финансовых/юридических гарантий; при сложных темах пиши «обсуди с бухгалтером/юристом».
- Не обещай нереалистичный заработок и не нарушай закон.
"""


async def complete_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    user_text: str,
    timeout_sec: int = 90,
) -> str:
    """Вызывает Chat Completions API (OpenAI или совместимый сервер)."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_RU},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            raw = await resp.text()
            if resp.status != 200:
                logger.warning("OpenAI API error %s: %s", resp.status, raw[:500])
                raise RuntimeError(f"API вернуло {resp.status}")

            data = json.loads(raw)
            choices = data.get("choices")
            if not choices:
                raise RuntimeError("Пустой ответ от API")
            message = choices[0].get("message") or {}
            content = message.get("content")
            if not content:
                raise RuntimeError("Нет текста в ответе")
            return str(content).strip()


def split_for_telegram(text: str, max_len: int = 4000) -> list[str]:
    """Делит длинный текст на части под лимит Telegram (4096)."""
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []

    parts: list[str] = []
    rest = text
    while rest:
        chunk = rest[:max_len]
        # резать по последнему переносу внутри chunk
        if len(rest) > max_len:
            cut = chunk.rfind("\n")
            if cut > max_len // 2:
                chunk = rest[: cut + 1]
        parts.append(chunk.rstrip())
        rest = rest[len(chunk) :].lstrip()
    return parts
