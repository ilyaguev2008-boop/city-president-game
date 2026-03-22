from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from text_utils import clean_title_for_post, sanitize_post_text, strip_urls

logger = logging.getLogger(__name__)


def _parse_openai_error_body(raw: str) -> str:
    """Текст ошибки из JSON ответа OpenAI-совместимого API."""
    if not raw.strip():
        return "(пустой ответ)"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()[:400]
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("code") or str(err)
        typ = err.get("type") or err.get("param")
        if typ:
            return f"{msg} ({typ})"[:400]
        return str(msg)[:400]
    if isinstance(err, str):
        return err[:400]
    return raw.strip()[:400]

NEWS_REWRITE_SYSTEM_RU = """Ты редактор новостей для Telegram-канала.

Перескажи материал на русском языке для поста.

Правила:
- 2–4 коротких абзаца, без хэштегов и без заголовка уровня Markdown (#).
- Не вставляй ссылки, URL и фразы вроде «читайте по ссылке».
- Не выдумывай факты; если чего-то нет в тексте — не дополняй.
- Сохраняй нейтральный тон новости.
- Убери из текста: призывы подписаться, рекламу, «читайте также», подписи к фото без фактов,
  хлебные крошки, теги, служебные пометки редакции — оставь только суть новости.
- Не добавляй эмодзи и декоративные символы, кроме обычных знаков препинания."""

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
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    detail = _parse_openai_error_body(raw)
                    logger.warning(
                        "Chat API HTTP %s %s: %s",
                        resp.status,
                        url,
                        raw[:800],
                    )
                    raise RuntimeError(f"HTTP {resp.status}: {detail}")

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Некорректный JSON от API: {raw[:200]}") from exc
                choices = data.get("choices")
                if not choices:
                    raise RuntimeError(f"Нет choices в ответе: {raw[:300]}")
                message = choices[0].get("message") or {}
                content = message.get("content")
                if not content:
                    # Некоторые модели отдают refusal / tool_calls
                    if message.get("refusal"):
                        raise RuntimeError(f"Модель отказалась: {message.get('refusal')}")
                    raise RuntimeError("Нет текста в ответе")
                return str(content).strip()
    except aiohttp.ClientError as exc:
        logger.warning("Сеть при запросе к ИИ: %s", exc)
        raise RuntimeError(f"Сеть: {exc}") from exc


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
    title = clean_title_for_post(title)
    body = sanitize_post_text(strip_urls(body))[:12000]
    user_text = f"Заголовок:\n{title}\n\nТекст:\n{body}"
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
