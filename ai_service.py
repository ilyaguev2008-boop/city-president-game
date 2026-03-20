from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

NEWS_REWRITE_SYSTEM_RU = """Ты редактор новостей для Telegram-канала.

Перескажи материал на русском языке для поста.

Правила:
- 2–4 коротких абзаца, без хэштегов и без заголовка уровня Markdown (#).
- Не вставляй ссылки, URL и фразы вроде «читайте по ссылке».
- Не выдумывай факты; если чего-то нет в тексте — не дополняй.
- Сохраняй нейтральный тон новости."""

SYSTEM_PROMPT_RU = """Ты дружелюбный AI-помощник для владельцев Telegram-каналов, которые используют бота автопостинга из своих источников новостей.

Помогаешь с: подключением бота к каналу, правами администратора, поиском ленты новостей на сайтах СМИ, настройкой сценариев постинга, пониманием работы разделов «Мои каналы», «Источники новостей», «Черновики».

Правила:
- Отвечай на русском, кратко и по делу, списками где уместно.
- Если не хватает контекста — задай 1–3 уточняющих вопроса.
- Не обещай обход правил Telegram и сайтов; про авторские права на контент источников — кратко и нейтрально, без юридических гарантий.
"""


async def complete_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    user_text: str,
    timeout_sec: int = 90,
    system_prompt: str | None = None,
) -> str:
    """Вызывает Chat Completions API (OpenAI или совместимый сервер)."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    system = system_prompt or SYSTEM_PROMPT_RU
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
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


async def rewrite_news_ru(
    *,
    api_key: str,
    base_url: str,
    model: str,
    title: str,
    body: str,
    timeout_sec: int = 90,
) -> str:
    """Пересказ новости на русском для поста (без ссылок в тексте на стороне модели)."""
    user_text = f"Заголовок:\n{title}\n\nТекст:\n{body[:12000]}"
    return await complete_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        user_text=user_text,
        timeout_sec=timeout_sec,
        system_prompt=NEWS_REWRITE_SYSTEM_RU,
    )


def split_for_telegram(text: str, max_len: int = 4000) -> list[str]:
    """Делит длинный текст на части под лимит Telegram (4096)."""
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []

    parts: list[str] = []
    rest = text
    while rest:
        chunk = rest[:max_len]
        if len(rest) > max_len:
            cut = chunk.rfind("\n")
            if cut > max_len // 2:
                chunk = rest[: cut + 1]
        parts.append(chunk.rstrip())
        rest = rest[len(chunk) :].lstrip()
    return parts
